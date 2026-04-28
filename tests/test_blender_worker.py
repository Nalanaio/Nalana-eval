"""Blender subprocess integration tests.

Spawns a real `blender --background --python single_run.py` process and
verifies the full pipeline end-to-end:
  scene reset → step execution → snapshot capture → (optional) screenshot render

Auto-skipped when the `blender` binary is not found on PATH or $BLENDER_BIN.
Run explicitly with:
  pytest tests/ -m blender_worker
Exclude with:
  pytest tests/ -m "not blender_worker"
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

_BLENDER_BIN: str = os.environ.get("BLENDER_BIN", "blender")
_SINGLE_RUN: str = str(
    Path(__file__).parent.parent / "nalana_eval" / "workers" / "single_run.py"
)
_RUNTIME_PATH: str = str(Path(__file__).parent.parent / "nalana_eval")


def _blender_available() -> bool:
    try:
        r = subprocess.run(
            [_BLENDER_BIN, "--version"],
            capture_output=True,
            timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.blender_worker

if not _blender_available():
    pytest.skip("blender binary not on PATH", allow_module_level=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_CASE: dict = {"id": "BW-TEST", "initial_scene": {}}


def _run_case(
    case_dict: dict,
    steps: list,
    *,
    require_screenshot: bool = False,
    timeout: int = 90,
) -> dict:
    """Run a single case via single_run.py inside a real Blender subprocess.

    Returns the parsed output dict, with an extra ``_artifacts_dir`` key so
    callers can inspect files written to disk.
    """
    with tempfile.TemporaryDirectory(prefix="nalana_blender_test_") as tmpdir:
        artifacts_dir = os.path.join(tmpdir, "artifacts")
        os.makedirs(artifacts_dir)

        case = dict(case_dict)
        case.setdefault("artifact_policy", {})["require_screenshot"] = require_screenshot

        msg = {
            "case": case,
            "normalized_steps": steps,
            "attempt_index": 0,
            "output_dir": artifacts_dir,
        }

        input_path = os.path.join(tmpdir, "input.json")
        output_path = os.path.join(tmpdir, "output.json")

        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(msg, f)

        env = os.environ.copy()
        env["NALANA_EVAL_RUNTIME_PATH"] = _RUNTIME_PATH

        proc = subprocess.run(
            [
                _BLENDER_BIN, "--background",
                "--python", _SINGLE_RUN,
                "--", input_path, output_path,
            ],
            env=env,
            timeout=timeout,
            capture_output=True,
            text=True,
        )

        assert os.path.exists(output_path), (
            f"single_run.py produced no output.json "
            f"(returncode={proc.returncode})\n"
            f"stderr (last 800 chars):\n{proc.stderr[-800:]}"
        )

        with open(output_path, encoding="utf-8") as f:
            result = json.load(f)

        # Expose artifacts dir for file-existence assertions.
        result["_artifacts_dir"] = artifacts_dir
        return result


# ---------------------------------------------------------------------------
# Tests — scene state
# ---------------------------------------------------------------------------


def test_empty_steps_empty_scene():
    """No steps → factory-empty scene; snapshot should report 0 mesh objects."""
    result = _run_case(_BASE_CASE, [])
    assert result["ok"] is True
    assert result["snapshot"]["total_mesh_objects"] == 0


def test_add_cube():
    result = _run_case(_BASE_CASE, [{"kind": "ADD_MESH", "args": {"primitive": "CUBE"}}])
    assert result["ok"] is True
    snap = result["snapshot"]
    assert snap["total_mesh_objects"] == 1
    assert snap["total_vertices"] == 8
    assert snap["total_faces"] == 6
    assert snap["quad_ratio"] == pytest.approx(1.0)
    assert snap["manifold"] is True


def test_add_uv_sphere():
    result = _run_case(
        _BASE_CASE,
        [{"kind": "ADD_MESH", "args": {"primitive": "UV_SPHERE", "segments": 8, "ring_count": 4}}],
    )
    assert result["ok"] is True
    assert result["snapshot"]["total_mesh_objects"] == 1


def test_add_cylinder():
    result = _run_case(
        _BASE_CASE,
        [{"kind": "ADD_MESH", "args": {"primitive": "CYLINDER", "vertices": 6}}],
    )
    assert result["ok"] is True
    assert result["snapshot"]["total_mesh_objects"] == 1


def test_translate_after_add():
    steps = [
        {"kind": "ADD_MESH", "args": {"primitive": "CUBE"}},
        {"kind": "TRANSLATE", "args": {"value": [2.0, 0.0, 0.0]}},
    ]
    result = _run_case(_BASE_CASE, steps)
    assert result["ok"] is True
    loc = result["snapshot"]["mesh_objects"][0]["location"]
    assert loc[0] == pytest.approx(2.0, abs=0.01)


def test_initial_scene_seed_object_present():
    """Objects in initial_scene should appear in the snapshot."""
    case = {
        "id": "BW-SEED",
        "initial_scene": {
            "objects": [{"primitive": "CUBE", "name": "SeedCube", "location": [0, 0, 0]}]
        },
    }
    result = _run_case(case, [])
    assert result["ok"] is True
    assert result["snapshot"]["total_mesh_objects"] == 1
    names = [m["name"] for m in result["snapshot"]["mesh_objects"]]
    assert "SeedCube" in names


# ---------------------------------------------------------------------------
# Tests — error handling
# ---------------------------------------------------------------------------


def test_invalid_step_kind_returns_failure():
    steps = [{"kind": "NOT_A_REAL_COMMAND", "args": {}}]
    result = _run_case(_BASE_CASE, steps)
    assert result["ok"] is False
    assert result["failure_class"] == "EXECUTION_ERROR"


def test_execution_error_does_not_crash_worker():
    """Worker should write output.json even when a step raises."""
    steps = [
        {"kind": "ADD_MESH", "args": {"primitive": "CUBE"}},
        {"kind": "NOT_A_REAL_COMMAND", "args": {}},
    ]
    result = _run_case(_BASE_CASE, steps)
    # Output should exist with ok=False — worker must not crash without output.
    assert isinstance(result["ok"], bool)


# ---------------------------------------------------------------------------
# Tests — file output
# ---------------------------------------------------------------------------


def test_scene_stats_json_written():
    """scene_stats JSON must be written and parseable."""
    result = _run_case(_BASE_CASE, [{"kind": "ADD_MESH", "args": {"primitive": "CUBE"}}])
    assert result["scene_stats_path"] != ""
    assert os.path.exists(result["scene_stats_path"])

    with open(result["scene_stats_path"], encoding="utf-8") as f:
        stats = json.load(f)
    assert stats["total_mesh_objects"] == 1


def test_screenshot_rendered():
    """screenshot PNG must exist and be non-empty.

    Requires a virtual framebuffer (DISPLAY env var set).  In the Docker
    container the entrypoint starts Xvfb on :99 before running pytest.
    """
    result = _run_case(
        _BASE_CASE,
        [{"kind": "ADD_MESH", "args": {"primitive": "CUBE"}}],
        require_screenshot=True,
    )
    assert result["ok"] is True, f"execution failed: {result.get('error')}"
    assert result["screenshot_path"] != "", "screenshot_path should be populated"
    assert os.path.exists(result["screenshot_path"]), "screenshot PNG must exist on disk"
    assert os.path.getsize(result["screenshot_path"]) > 512, "screenshot PNG is unexpectedly small"
