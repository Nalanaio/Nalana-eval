"""Unit tests for csv_db.py — uses tmp_path to avoid touching db/."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

import nalana_eval.csv_db as db_mod
from nalana_eval.csv_db import (
    ATTEMPTS_FIELDS,
    JUDGE_VS_HUMAN_FIELDS,
    RUNS_FIELDS,
    append_attempt,
    append_judge_vs_human,
    append_run,
    query_attempts,
    query_runs,
    update_human_review,
)
from nalana_eval.schema import (
    ArtifactPolicy,
    AttemptArtifact,
    BenchmarkRun,
    BenchmarkRunConfig,
    Category,
    Difficulty,
    FailureClass,
    HardConstraints,
    InitialScene,
    JudgePolicy,
    RunMetrics,
    SceneSnapshot,
    StyleIntent,
    TaskFamily,
    TestCaseCard,
    TopologyPolicy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Redirect all CSV paths to a temp directory for each test."""
    monkeypatch.setattr(db_mod, "_DB_DIR", tmp_path)
    monkeypatch.setattr(db_mod, "_RUNS_CSV", tmp_path / "runs.csv")
    monkeypatch.setattr(db_mod, "_ATTEMPTS_CSV", tmp_path / "attempts.csv")
    monkeypatch.setattr(db_mod, "_JUDGE_VS_HUMAN_CSV", tmp_path / "judge_vs_human.csv")
    yield tmp_path


def _make_run(run_id: str = "run-test-001") -> BenchmarkRun:
    return BenchmarkRun(
        run_id=run_id,
        run_group_id="grp-001",
        timestamp_utc="2026-04-26T00:00:00Z",
        model_id="mock",
        suite_id="test-suite",
        config=BenchmarkRunConfig(pass_at_k=3, temperature=0.7, seed=42),
        metrics=RunMetrics(
            total_cases=5,
            total_attempts=15,
            execution_success_rate=0.8,
            hard_pass_rate=0.6,
            topology_pass_rate=0.9,
            avg_soft_score=0.75,
            pass_at_1=0.6,
            pass_at_3=0.8,
        ),
    )


def _make_case() -> TestCaseCard:
    return TestCaseCard(
        id="CV-TEST-001",
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
        artifact_policy=ArtifactPolicy(),
    )


def _make_attempt(case_id: str = "CV-TEST-001", attempt_index: int = 0) -> AttemptArtifact:
    return AttemptArtifact(
        case_id=case_id,
        attempt_index=attempt_index,
        model_id="mock",
        prompt_used="Add a cube",
        parse_success=True,
        safety_success=True,
        execution_success=True,
        passed_hard_constraints=True,
        passed_topology=True,
        soft_score=0.9,
        pass_overall=True,
        failure_class=FailureClass.NONE,
        scene_snapshot=SceneSnapshot(
            total_objects=1,
            total_mesh_objects=1,
            total_vertices=8,
            total_faces=6,
            quad_ratio=1.0,
            manifold=True,
            bbox_min=[-1.0, -1.0, -1.0],
            bbox_max=[1.0, 1.0, 1.0],
        ),
        model_latency_ms=120.0,
        execution_latency_ms=800.0,
    )


# ---------------------------------------------------------------------------
# append_run
# ---------------------------------------------------------------------------


def test_append_run_creates_file_with_header(isolated_db):
    run = _make_run()
    append_run(run)

    runs_csv = isolated_db / "runs.csv"
    assert runs_csv.exists()

    with open(runs_csv, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["run_id"] == "run-test-001"
    assert rows[0]["model_id"] == "mock"


def test_append_run_multiple(isolated_db):
    append_run(_make_run("run-001"))
    append_run(_make_run("run-002"))

    rows = query_runs()
    assert len(rows) == 2
    assert {r["run_id"] for r in rows} == {"run-001", "run-002"}


def test_append_run_all_fields_present(isolated_db):
    append_run(_make_run())
    rows = query_runs()
    for field in RUNS_FIELDS:
        assert field in rows[0], f"Missing field: {field}"


# ---------------------------------------------------------------------------
# append_attempt
# ---------------------------------------------------------------------------


def test_append_attempt_creates_file(isolated_db):
    attempt = _make_attempt()
    case = _make_case()
    append_attempt("run-001", attempt, case)

    attempts_csv = isolated_db / "attempts.csv"
    assert attempts_csv.exists()

    rows = query_attempts()
    assert len(rows) == 1
    assert rows[0]["case_id"] == "CV-TEST-001"
    assert rows[0]["attempt_index"] == "0"


def test_append_attempt_all_fields_present(isolated_db):
    append_attempt("run-001", _make_attempt(), _make_case())
    rows = query_attempts()
    for field in ATTEMPTS_FIELDS:
        assert field in rows[0], f"Missing field: {field}"


def test_append_attempt_multiple_attempts(isolated_db):
    case = _make_case()
    for i in range(3):
        append_attempt("run-001", _make_attempt(attempt_index=i), case)
    rows = query_attempts(run_id="run-001")
    assert len(rows) == 3
    indices = {r["attempt_index"] for r in rows}
    assert indices == {"0", "1", "2"}


# ---------------------------------------------------------------------------
# query_runs / query_attempts filters
# ---------------------------------------------------------------------------


def test_query_runs_filter_by_model(isolated_db):
    r1 = _make_run("run-001")
    r2 = _make_run("run-002")
    # Patch model_id in the second run object
    r2 = r2.model_copy(update={"model_id": "gpt-4o"})
    append_run(r1)
    append_run(r2)

    rows = query_runs(model_id="mock")
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run-001"


def test_query_runs_last_n(isolated_db):
    for i in range(5):
        append_run(_make_run(f"run-{i:03d}"))
    rows = query_runs(last_n=3)
    assert len(rows) == 3
    assert rows[-1]["run_id"] == "run-004"


def test_query_attempts_filter_by_case(isolated_db):
    case = _make_case()
    append_attempt("run-001", _make_attempt("CV-TEST-001"), case)
    case2 = case.model_copy(update={"id": "CV-TEST-002"})
    append_attempt("run-001", _make_attempt("CV-TEST-002"), case2)

    rows = query_attempts(case_id="CV-TEST-001")
    assert len(rows) == 1
    assert rows[0]["case_id"] == "CV-TEST-001"


# ---------------------------------------------------------------------------
# update_human_review
# ---------------------------------------------------------------------------


def test_update_human_review_modifies_row(isolated_db):
    append_attempt("run-001", _make_attempt(), _make_case())

    update_human_review(
        run_id="run-001",
        case_id="CV-TEST-001",
        attempt_index=0,
        override="agree",
        corrected_semantic=None,
        corrected_aesthetic=None,
        corrected_professional=None,
        reviewer="alice",
        timestamp_utc="2026-04-26T10:00:00Z",
        note="Looks good",
    )

    rows = query_attempts(run_id="run-001")
    assert rows[0]["judge_human_override"] == "agree"
    assert rows[0]["judge_human_reviewer"] == "alice"
    assert rows[0]["judge_human_note"] == "Looks good"


def test_update_human_review_no_match_is_noop(isolated_db):
    append_attempt("run-001", _make_attempt(), _make_case())
    # Update for a non-existent row — should not crash, just log warning
    update_human_review(
        run_id="run-999",
        case_id="CV-MISSING",
        attempt_index=0,
        override="agree",
        corrected_semantic=None,
        corrected_aesthetic=None,
        corrected_professional=None,
        reviewer="bob",
        timestamp_utc="2026-04-26T10:00:00Z",
    )
    rows = query_attempts(run_id="run-001")
    assert rows[0]["judge_human_override"] == ""


def test_update_human_review_with_corrected_scores(isolated_db):
    append_attempt("run-001", _make_attempt(), _make_case())

    update_human_review(
        run_id="run-001",
        case_id="CV-TEST-001",
        attempt_index=0,
        override="disagree",
        corrected_semantic=2.0,
        corrected_aesthetic=3.0,
        corrected_professional=4.0,
        reviewer="charlie",
        timestamp_utc="2026-04-26T11:00:00Z",
    )

    rows = query_attempts(run_id="run-001")
    assert rows[0]["judge_human_corrected_semantic"] == "2.0"
    assert rows[0]["judge_human_corrected_aesthetic"] == "3.0"
    assert rows[0]["judge_human_corrected_professional"] == "4.0"


# ---------------------------------------------------------------------------
# append_judge_vs_human
# ---------------------------------------------------------------------------


def test_append_judge_vs_human(isolated_db):
    event: Dict[str, Any] = {
        "event_timestamp_utc": "2026-04-26T12:00:00Z",
        "run_id": "run-001",
        "case_id": "CV-TEST-001",
        "attempt_index": 0,
        "judge_model": "gpt-4o",
        "judge_judged_under_standard": "geometric",
        "judge_semantic": 4.0,
        "judge_aesthetic": 3.5,
        "judge_professional": 4.5,
        "human_corrected_semantic": 3.0,
        "human_corrected_aesthetic": 3.0,
        "human_corrected_professional": 4.0,
        "delta_semantic": -1.0,
        "delta_aesthetic": -0.5,
        "delta_professional": -0.5,
        "human_reviewer": "alice",
        "human_note": "Overestimated concept",
        "screenshot_path": "/tmp/shot.png",
        "prompt_used": "Add a cube",
        "case_style_intent_explicit": False,
    }
    append_judge_vs_human(event)

    jvh_csv = isolated_db / "judge_vs_human.csv"
    assert jvh_csv.exists()
    with open(jvh_csv, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run-001"
    assert rows[0]["human_reviewer"] == "alice"
