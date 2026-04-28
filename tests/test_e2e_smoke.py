"""End-to-end smoke test: MockRunner + stubbed Blender worker → full pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

import nalana_eval.csv_db as db_mod
from nalana_eval.harness import Harness
from nalana_eval.runners.mock_runner import MockRunner
from nalana_eval.schema import (
    ArtifactPolicy,
    BenchmarkRunConfig,
    Category,
    Difficulty,
    FailureClass,
    HardConstraints,
    InitialScene,
    JudgePolicy,
    StyleIntent,
    TaskFamily,
    TestCaseCard,
    TestSuite,
    TopologyPolicy,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_stub_snapshot(n_objects: int = 1) -> Dict[str, Any]:
    """Pre-canned SceneSnapshot dict that the stub Blender worker returns."""
    meshes = [
        {
            "name": f"Cube{i}",
            "object_type": "MESH",
            "vertex_count": 8,
            "edge_count": 12,
            "face_count": 6,
            "face_sizes": {"4": 6},
            "manifold": True,
            "bbox_min": [-1.0, -1.0, -1.0],
            "bbox_max": [1.0, 1.0, 1.0],
            "location": [0.0, 0.0, 0.0],
            "rotation": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "materials": [],
        }
        for i in range(n_objects)
    ]
    return {
        "active_object": "Cube0",
        "total_objects": n_objects,
        "total_mesh_objects": n_objects,
        "total_vertices": 8 * n_objects,
        "total_faces": 6 * n_objects,
        "quad_ratio": 1.0,
        "manifold": True,
        "bbox_min": [-1.0, -1.0, -1.0],
        "bbox_max": [1.0, 1.0, 1.0],
        "mesh_objects": meshes,
    }


def _stub_blender(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Fake Blender worker that always succeeds with one cube."""
    return {
        "ok": True,
        "execution_latency_ms": 50.0,
        "snapshot": _make_stub_snapshot(n_objects=1),
        "screenshot_path": "",
        "scene_stats_path": "",
    }


def _make_five_cases() -> List[TestCaseCard]:
    cases = []
    for i in range(1, 6):
        cases.append(TestCaseCard(
            id=f"CV-SMOKE-{i:03d}",
            category=Category.OBJECT_CREATION,
            difficulty=Difficulty.SHORT,
            task_family=TaskFamily.PRIMITIVE_CREATION,
            prompt_variants=["Add a cube"],
            initial_scene=InitialScene(),
            hard_constraints=HardConstraints(),
            topology_policy=TopologyPolicy(),
            soft_constraints=[],
            style_intent=StyleIntent(),
            judge_policy=JudgePolicy.SKIP,
            artifact_policy=ArtifactPolicy(require_screenshot=False, write_scene_stats=False),
        ))
    return cases


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_DB_DIR", tmp_path)
    monkeypatch.setattr(db_mod, "_RUNS_CSV", tmp_path / "runs.csv")
    monkeypatch.setattr(db_mod, "_ATTEMPTS_CSV", tmp_path / "attempts.csv")
    monkeypatch.setattr(db_mod, "_JUDGE_VS_HUMAN_CSV", tmp_path / "judge_vs_human.csv")
    yield tmp_path


# ---------------------------------------------------------------------------
# Smoke: 5 cases, MockRunner, stub Blender
# ---------------------------------------------------------------------------


def test_e2e_five_cases_all_pass(tmp_path):
    suite = TestSuite(
        suite_id="smoke-suite",
        cases=_make_five_cases(),
    )
    runner = MockRunner(model_id="mock")
    config = BenchmarkRunConfig(
        cases=5,
        pass_at_k=1,
        models=["mock"],
        simple_mode=True,
        seed=0,
    )

    harness = Harness(
        suite=suite,
        runners=[runner],
        config=config,
        output_base_dir=str(tmp_path / "artifacts"),
    )

    with patch.object(harness, "_blender_submit", side_effect=_stub_blender):
        runs = harness.run()

    assert len(runs) == 1
    run = runs[0]
    assert run.model_id == "mock"

    # All 5 attempts should have passed
    real_attempts = [a for a in run.attempts if not a.is_honeypot]
    assert len(real_attempts) == 5

    for attempt in real_attempts:
        assert attempt.parse_success is True
        assert attempt.safety_success is True
        assert attempt.execution_success is True
        assert attempt.passed_hard_constraints is True
        assert attempt.pass_overall is True
        assert attempt.failure_class == FailureClass.NONE


def test_e2e_metrics_populated(tmp_path):
    suite = TestSuite(suite_id="smoke-suite", cases=_make_five_cases())
    runner = MockRunner(model_id="mock")
    config = BenchmarkRunConfig(cases=5, pass_at_k=1, models=["mock"], simple_mode=True, seed=1)
    harness = Harness(
        suite=suite,
        runners=[runner],
        config=config,
        output_base_dir=str(tmp_path / "artifacts"),
    )

    with patch.object(harness, "_blender_submit", side_effect=_stub_blender):
        runs = harness.run()

    m = runs[0].metrics
    assert m.total_cases == 5
    assert m.execution_success_rate == pytest.approx(1.0)
    assert m.hard_pass_rate == pytest.approx(1.0)
    assert m.pass_at_1 == pytest.approx(1.0)


def test_e2e_blender_failure_recorded(tmp_path):
    """When Blender returns ok=False, attempt should fail with EXECUTION_ERROR."""
    def fail_blender(msg: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "ok": False,
            "execution_latency_ms": 10.0,
            "error": "Blender crashed",
            "snapshot": {},
            "screenshot_path": "",
            "scene_stats_path": "",
        }

    cases = _make_five_cases()[:1]
    suite = TestSuite(suite_id="smoke-fail", cases=cases)
    runner = MockRunner(model_id="mock")
    config = BenchmarkRunConfig(cases=1, pass_at_k=1, models=["mock"], simple_mode=True, seed=2)
    harness = Harness(
        suite=suite,
        runners=[runner],
        config=config,
        output_base_dir=str(tmp_path / "artifacts"),
    )

    with patch.object(harness, "_blender_submit", side_effect=fail_blender):
        runs = harness.run()

    attempt = runs[0].attempts[0]
    assert attempt.execution_success is False
    assert attempt.pass_overall is False
    assert attempt.failure_class == FailureClass.EXECUTION_ERROR


def test_e2e_parse_failure_no_blender_call(tmp_path):
    """When model output is unparseable, Blender should not be called."""
    cases = _make_five_cases()[:1]
    suite = TestSuite(suite_id="smoke-parse-fail", cases=cases)

    # MockRunner with unparseable payload
    runner = MockRunner(
        model_id="mock",
        payloads={"__default__": "NOT VALID JSON {{{{"},
    )
    config = BenchmarkRunConfig(cases=1, pass_at_k=1, models=["mock"], simple_mode=True, seed=3)
    harness = Harness(
        suite=suite,
        runners=[runner],
        config=config,
        output_base_dir=str(tmp_path / "artifacts"),
    )

    blender_call_count = 0

    def counting_blender(msg: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal blender_call_count
        blender_call_count += 1
        return _stub_blender(msg)

    with patch.object(harness, "_blender_submit", side_effect=counting_blender):
        runs = harness.run()

    assert blender_call_count == 0
    attempt = runs[0].attempts[0]
    assert attempt.parse_success is False
    assert attempt.failure_class == FailureClass.PARSE_ERROR


def test_e2e_pass_at_k_stops_early_on_success(tmp_path):
    """Pass@k=3 should stop at attempt_index=0 when first attempt passes."""
    cases = _make_five_cases()[:2]  # 2 cases
    suite = TestSuite(suite_id="smoke-passk", cases=cases)
    runner = MockRunner(model_id="mock")
    config = BenchmarkRunConfig(cases=2, pass_at_k=3, models=["mock"], simple_mode=True, seed=4)
    harness = Harness(
        suite=suite,
        runners=[runner],
        config=config,
        output_base_dir=str(tmp_path / "artifacts"),
    )

    with patch.object(harness, "_blender_submit", side_effect=_stub_blender):
        runs = harness.run()

    real_attempts = [a for a in runs[0].attempts if not a.is_honeypot]
    # Each case should complete in 1 attempt (pass@1=True → break)
    # So total real attempts = 2 (not 6)
    assert len(real_attempts) == 2
    for a in real_attempts:
        assert a.attempt_index == 0


def test_e2e_multiple_runners(tmp_path):
    """Two runners should produce two BenchmarkRun objects."""
    suite = TestSuite(suite_id="smoke-multi", cases=_make_five_cases())
    runner1 = MockRunner(model_id="mock-a")
    runner2 = MockRunner(model_id="mock-b")
    config = BenchmarkRunConfig(cases=5, pass_at_k=1, models=["mock-a", "mock-b"], simple_mode=True, seed=5)
    harness = Harness(
        suite=suite,
        runners=[runner1, runner2],
        config=config,
        output_base_dir=str(tmp_path / "artifacts"),
    )

    with patch.object(harness, "_blender_submit", side_effect=_stub_blender):
        runs = harness.run()

    assert len(runs) == 2
    model_ids = {r.model_id for r in runs}
    assert model_ids == {"mock-a", "mock-b"}
