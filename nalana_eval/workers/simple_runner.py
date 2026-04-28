"""Simple Mode: one Blender subprocess per case (--simple-mode)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60  # seconds per case


class SimpleRunner:
    """Runs each case in a fresh Blender subprocess.

    Slower than WorkerPool but guarantees a clean environment per case.
    """

    def __init__(
        self,
        blender_bin: str = "blender",
        runtime_path: Optional[str] = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._blender_bin = blender_bin
        self._timeout = timeout
        self._single_run_script = str(
            Path(__file__).parent / "single_run.py"
        )
        resolved = runtime_path or str(Path(__file__).parent.parent)
        self._env = dict(os.environ)
        self._env["NALANA_EVAL_RUNTIME_PATH"] = resolved

    def run(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Run one case. Returns result dict from single_run.py."""
        with tempfile.TemporaryDirectory(prefix="nalana_simple_") as tmpdir:
            input_path = os.path.join(tmpdir, "input.json")
            output_path = os.path.join(tmpdir, "output.json")

            with open(input_path, "w", encoding="utf-8") as f:
                json.dump(msg, f)

            cmd = [
                self._blender_bin,
                "--background",
                "--python",
                self._single_run_script,
                "--",
                input_path,
                output_path,
            ]
            logger.debug("SimpleRunner: %s", " ".join(cmd))

            try:
                subprocess.run(
                    cmd,
                    env=self._env,
                    timeout=self._timeout,
                    check=False,
                    stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired:
                logger.error("SimpleRunner timed out after %ds", self._timeout)
                return self._timeout_result()
            except Exception as exc:
                logger.error("SimpleRunner subprocess error: %s", exc)
                return self._error_result(str(exc))

            if not os.path.exists(output_path):
                return self._error_result("Blender produced no output file")

            try:
                with open(output_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                return self._error_result(f"Output JSON parse error: {exc}")

    @staticmethod
    def _timeout_result() -> Dict[str, Any]:
        return {
            "ok": False,
            "error": "Blender subprocess timed out",
            "failure_class": "WORKER_TIMEOUT",
            "snapshot": {},
            "screenshot_path": "",
            "scene_stats_path": "",
            "execution_latency_ms": 0.0,
        }

    @staticmethod
    def _error_result(msg: str) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": msg,
            "failure_class": "EXECUTION_ERROR",
            "snapshot": {},
            "screenshot_path": "",
            "scene_stats_path": "",
            "execution_latency_ms": 0.0,
        }
