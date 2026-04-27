"""Persistent Blender worker pool.

Manages N `blender --background --python worker_loop.py` processes.
Each worker handles one case at a time; workers are round-robin allocated
via a thread-safe queue.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PING_TIMEOUT = 5.0      # seconds to wait for pong
_CASE_TIMEOUT = 120.0    # seconds before a case run is considered hung
_HEALTH_CHECK_INTERVAL = 100  # submit calls between health checks


class _Worker:
    """Represents a single Blender subprocess worker."""

    def __init__(
        self,
        worker_id: int,
        blender_bin: str,
        worker_script: str,
        env: Dict[str, str],
    ) -> None:
        self.worker_id = worker_id
        self._blender_bin = blender_bin
        self._worker_script = worker_script
        self._env = env
        self._proc: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self._submit_count = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        cmd = [
            self._blender_bin,
            "--background",
            "--python",
            self._worker_script,
        ]
        logger.debug("Spawning worker %d: %s", self.worker_id, " ".join(cmd))
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # let stderr flow to terminal for debug
            text=True,
            bufsize=1,
            env=self._env,
        )

    def _is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def ping(self, timeout: float = _PING_TIMEOUT) -> bool:
        """Send a ping and wait for pong. Returns False if worker is dead or unresponsive."""
        if not self._is_alive():
            return False
        try:
            assert self._proc is not None
            self._proc.stdin.write(json.dumps({"command": "ping"}) + "\n")  # type: ignore[union-attr]
            self._proc.stdin.flush()  # type: ignore[union-attr]

            import select  # noqa: PLC0415
            if sys.platform != "win32":
                ready, _, _ = select.select([self._proc.stdout], [], [], timeout)
                if not ready:
                    return False
            line = self._proc.stdout.readline()  # type: ignore[union-attr]
            data = json.loads(line.strip())
            return bool(data.get("pong"))
        except Exception as exc:
            logger.warning("Worker %d ping failed: %s", self.worker_id, exc)
            return False

    def run_case(self, msg: Dict[str, Any], timeout: float = _CASE_TIMEOUT) -> Dict[str, Any]:
        """Send run_case message and block until result received."""
        if not self._is_alive():
            self.start()

        assert self._proc is not None
        payload = dict(msg)
        payload["command"] = "run_case"

        try:
            self._proc.stdin.write(json.dumps(payload) + "\n")  # type: ignore[union-attr]
            self._proc.stdin.flush()  # type: ignore[union-attr]
        except BrokenPipeError:
            logger.warning("Worker %d stdin pipe broken; restarting", self.worker_id)
            self.restart()
            return self._error_result("Worker pipe broken; restart triggered")

        # Read response with timeout via threading
        result_holder: List[Optional[str]] = [None]
        error_holder: List[Optional[Exception]] = [None]

        def _read() -> None:
            try:
                line = self._proc.stdout.readline()  # type: ignore[union-attr]
                result_holder[0] = line
            except Exception as exc:
                error_holder[0] = exc

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            logger.error("Worker %d timed out after %.0fs; restarting", self.worker_id, timeout)
            self.restart()
            return self._error_result(f"Worker timed out after {timeout}s")

        if error_holder[0]:
            logger.error("Worker %d read error: %s", self.worker_id, error_holder[0])
            return self._error_result(str(error_holder[0]))

        line = result_holder[0] or ""
        if not line.strip():
            return self._error_result("Worker returned empty response")

        try:
            return json.loads(line.strip())
        except json.JSONDecodeError as exc:
            logger.error("Worker %d bad JSON response: %s | line=%r", self.worker_id, exc, line[:200])
            return self._error_result(f"Worker bad JSON: {exc}")

    def restart(self) -> None:
        logger.info("Restarting worker %d", self.worker_id)
        self.shutdown()
        self.start()

    def shutdown(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write(json.dumps({"command": "exit"}) + "\n")  # type: ignore[union-attr]
                self._proc.stdin.flush()  # type: ignore[union-attr]
                self._proc.wait(timeout=5.0)
            except Exception:
                self._proc.kill()
        self._proc = None

    @staticmethod
    def _error_result(msg: str) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": msg,
            "failure_class": "WORKER_TIMEOUT",
            "snapshot": {},
            "screenshot_path": "",
            "scene_stats_path": "",
            "execution_latency_ms": 0.0,
        }


class WorkerPool:
    """Thread-safe pool of Blender worker processes."""

    def __init__(
        self,
        n_workers: int = 1,
        blender_bin: str = "blender",
        runtime_path: Optional[str] = None,
        output_dir: str = "/tmp",
    ) -> None:
        self._n_workers = max(1, n_workers)
        self._blender_bin = blender_bin
        self._output_dir = output_dir

        worker_script = str(
            Path(__file__).parent / "worker_loop.py"
        )

        env = dict(os.environ)
        resolved_runtime = runtime_path or str(Path(__file__).parent.parent)
        env["NALANA_EVAL_RUNTIME_PATH"] = resolved_runtime

        self._workers = [
            _Worker(i, blender_bin, worker_script, env)
            for i in range(self._n_workers)
        ]
        self._available: queue.Queue[_Worker] = queue.Queue()
        self._total_submitted = 0
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        for w in self._workers:
            w.start()
            self._available.put(w)
        self._started = True
        logger.info("WorkerPool started with %d workers", self._n_workers)

    def submit(self, msg: Dict[str, Any], timeout: float = _CASE_TIMEOUT) -> Dict[str, Any]:
        """Submit a case and block until the result is available."""
        if not self._started:
            self.start()

        worker = self._available.get()
        try:
            self._total_submitted += 1
            if self._total_submitted % _HEALTH_CHECK_INTERVAL == 0:
                if not worker.ping():
                    logger.warning("Worker %d health check failed; restarting", worker.worker_id)
                    worker.restart()
            return worker.run_case(msg, timeout=timeout)
        finally:
            self._available.put(worker)

    def shutdown(self) -> None:
        for w in self._workers:
            try:
                w.shutdown()
            except Exception as exc:
                logger.warning("Error shutting down worker %d: %s", w.worker_id, exc)
        logger.info("WorkerPool shut down")

    def __enter__(self) -> "WorkerPool":
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.shutdown()
