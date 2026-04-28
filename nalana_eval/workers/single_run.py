"""Single-shot Blender runner for --simple-mode. Launched as:
    blender --background --python single_run.py -- input.json output.json

Reads one case from input.json, writes result to output.json, then exits.
No stdin loop — completely isolated run per case.
"""
import json
import os
import sys

# Let Blender find dispatcher / scene_capture / screenshot from nalana_eval/
_runtime = os.environ.get("NALANA_EVAL_RUNTIME_PATH", "")
if _runtime and _runtime not in sys.path:
    sys.path.insert(0, _runtime)

import bpy  # type: ignore[import]  # noqa: E402

import dispatcher  # type: ignore[import]  # noqa: E402
import scene_capture  # type: ignore[import]  # noqa: E402
import screenshot  # type: ignore[import]  # noqa: E402

# Import run_one_case logic (shared with worker_loop)
# We re-implement inline to avoid importing worker_loop (which starts a loop).
import time


def _log(msg: str) -> None:
    sys.stderr.write(f"[single_run] {msg}\n")
    sys.stderr.flush()


def run_one_case(msg: dict) -> dict:
    case = msg["case"]
    steps = msg.get("normalized_steps", [])
    attempt_index = int(msg.get("attempt_index", 0))
    output_dir = msg.get("output_dir", "/tmp")
    case_id = case.get("id", "unknown")

    started = time.perf_counter()
    dispatcher.reset_scene(case.get("initial_scene", {}))

    execution_success = True
    error_msg = None
    try:
        dispatcher.execute_normalized_steps(steps)
    except Exception as exc:
        execution_success = False
        error_msg = str(exc)
        _log(f"execution error: {exc}")

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    snapshot = scene_capture.capture()

    stats_dir = os.path.join(output_dir, "scene_stats")
    os.makedirs(stats_dir, exist_ok=True)
    stats_path = os.path.join(stats_dir, f"{case_id}_attempt_{attempt_index}.json")
    try:
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
    except Exception as exc:
        _log(f"failed to write scene stats: {exc}")
        stats_path = ""

    artifact_policy = (case.get("artifact_policy") or {})
    require_screenshot = artifact_policy.get("require_screenshot", True)
    screenshot_path = ""
    if require_screenshot:
        screenshots_dir = os.path.join(output_dir, "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshots_dir, f"{case_id}_attempt_{attempt_index}.png")
        try:
            screenshot.render_scene_to_png(screenshot_path, resolution=(800, 600))
        except Exception as exc:
            _log(f"screenshot failed: {exc}")
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
    # Blender passes script args after "--"
    try:
        sep = sys.argv.index("--")
        argv = sys.argv[sep + 1:]
    except ValueError:
        _log("usage: blender --background --python single_run.py -- input.json output.json")
        sys.exit(1)

    if len(argv) < 2:
        _log("usage: ... -- input.json output.json")
        sys.exit(1)

    input_path, output_path = argv[0], argv[1]

    try:
        with open(input_path, encoding="utf-8") as f:
            msg = json.load(f)
    except Exception as exc:
        _log(f"failed to read input: {exc}")
        sys.exit(1)

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

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    except Exception as exc:
        _log(f"failed to write output: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
