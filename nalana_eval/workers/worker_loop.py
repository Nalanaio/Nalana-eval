"""Persistent Blender worker script. Launched as:
    blender --background --python worker_loop.py

Reads JSON command lines from stdin, writes JSON results to stdout.
stderr is left un-piped so debug output flows to the terminal.

IMPORTANT: no print() — any stray write to stdout corrupts the protocol.
"""
import json
import os
import sys
import time

# Let Blender find dispatcher / scene_capture / screenshot from nalana_eval/
_runtime = os.environ.get("NALANA_EVAL_RUNTIME_PATH", "")
if _runtime and _runtime not in sys.path:
    sys.path.insert(0, _runtime)

import bpy  # type: ignore[import]  # noqa: E402

# These imports must succeed once runtime path is set
import dispatcher  # type: ignore[import]  # noqa: E402
import scene_capture  # type: ignore[import]  # noqa: E402
import screenshot  # type: ignore[import]  # noqa: E402


def _log(msg: str) -> None:
    sys.stderr.write(f"[worker_loop] {msg}\n")
    sys.stderr.flush()


def run_one_case(msg: dict) -> dict:
    case = msg["case"]
    steps = msg.get("normalized_steps", [])
    attempt_index = int(msg.get("attempt_index", 0))
    output_dir = msg.get("output_dir", "/tmp")
    case_id = case.get("id", "unknown")

    started = time.perf_counter()

    # 1. Reset scene to initial state
    dispatcher.reset_scene(case.get("initial_scene", {}))

    # 2. Execute normalized steps
    execution_success = True
    error_msg = None
    try:
        dispatcher.execute_normalized_steps(steps)
    except Exception as exc:
        execution_success = False
        error_msg = str(exc)
        _log(f"execution error for {case_id}: {exc}")

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    # 3. Capture scene snapshot
    snapshot = scene_capture.capture()

    # 4. Write scene stats JSON
    stats_dir = os.path.join(output_dir, "scene_stats")
    os.makedirs(stats_dir, exist_ok=True)
    stats_filename = f"{case_id}_attempt_{attempt_index}.json"
    stats_path = os.path.join(stats_dir, stats_filename)
    try:
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
    except Exception as exc:
        _log(f"failed to write scene stats: {exc}")
        stats_path = ""

    # 5. Render screenshot (only when execution succeeded or artifact_policy allows)
    artifact_policy = (case.get("artifact_policy") or {})
    require_screenshot = artifact_policy.get("require_screenshot", True)
    screenshot_path = ""
    if require_screenshot:
        os.makedirs(output_dir, exist_ok=True)
        screenshot_path = os.path.join(output_dir, f"{case_id}_attempt_{attempt_index}.png")
        try:
            screenshot.render_scene_to_png(screenshot_path, resolution=(800, 600))
        except Exception as exc:
            _log(f"screenshot failed for {case_id}: {exc}")
            screenshot_path = ""

    return {
        "ok": execution_success,
        "error": error_msg,
        "failure_class": "EXECUTION_ERROR" if not execution_success else "NONE",
        "snapshot": snapshot,
        "screenshot_path": screenshot_path,
        "scene_stats_path": stats_path,
        "execution_latency_ms": elapsed_ms,
    }


def main() -> None:
    _log("worker ready")
    while True:
        try:
            line = sys.stdin.readline()
        except (EOFError, OSError):
            break
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            _log(f"bad JSON from harness: {exc}")
            continue

        cmd = msg.get("command", "")

        if cmd == "exit":
            _log("received exit")
            break

        if cmd == "ping":
            sys.stdout.write(json.dumps({"pong": True}) + "\n")
            sys.stdout.flush()
            continue

        if cmd == "run_case":
            try:
                result = run_one_case(msg)
            except Exception as exc:
                result = {
                    "ok": False,
                    "error": str(exc),
                    "failure_class": "EXECUTION_ERROR",
                    "snapshot": {},
                    "screenshot_path": "",
                    "scene_stats_path": "",
                    "execution_latency_ms": 0.0,
                }
            sys.stdout.write(json.dumps(result) + "\n")
            sys.stdout.flush()
            continue

        _log(f"unknown command {cmd!r}")


if __name__ == "__main__":
    main()
