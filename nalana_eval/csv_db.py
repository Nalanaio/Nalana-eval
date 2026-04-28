"""Append-only CSV database for benchmark runs and attempts.

Schema: docs/CSV_SCHEMA.md
"""
from __future__ import annotations

import csv
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from nalana_eval.schema import AttemptArtifact, BenchmarkRun, TestCaseCard

logger = logging.getLogger(__name__)

_DB_DIR = Path("db")
_RUNS_CSV = _DB_DIR / "runs.csv"
_ATTEMPTS_CSV = _DB_DIR / "attempts.csv"
_JUDGE_VS_HUMAN_CSV = _DB_DIR / "judge_vs_human.csv"

# ---------------------------------------------------------------------------
# Field lists (authoritative source; matches CSV_SCHEMA.md)
# ---------------------------------------------------------------------------

RUNS_FIELDS = [
    "run_id", "run_group_id", "timestamp_utc", "model_id", "judge_model",
    "system_prompt_version", "prompt_template_version", "temperature", "seed",
    "pass_at_k", "total_cases", "total_attempts",
    "difficulty_dist", "category_dist",
    "execution_success_rate", "hard_pass_rate", "topology_pass_rate",
    "avg_soft_score", "pass_at_1", "pass_at_3",
    "avg_judge_semantic", "avg_judge_aesthetic", "avg_judge_professional",
    "judge_reliable", "judge_honeypot_catch_rate", "judge_calibration_drift",
    "avg_model_latency_ms", "avg_execution_latency_ms", "total_cost_usd",
    "total_duration_s", "report_md_path", "report_json_path",
    "git_commit", "cli_args", "notes",
]

ATTEMPTS_FIELDS = [
    "run_id", "case_id", "attempt_index", "model_id",
    "category", "difficulty", "task_family", "prompt_used",
    "parse_success", "safety_success", "execution_success",
    "passed_hard_constraints", "passed_topology", "pass_overall",
    "soft_score", "failure_class", "failure_reason",
    "total_objects", "total_mesh_objects", "total_vertices", "total_faces",
    "quad_ratio", "manifold",
    "bbox_min_x", "bbox_min_y", "bbox_min_z",
    "bbox_max_x", "bbox_max_y", "bbox_max_z",
    "judge_semantic", "judge_aesthetic", "judge_professional",
    "judge_stddev", "judge_judged_under_standard",
    "judge_detected_style", "judge_detected_concept",
    "judge_style_alignment_pass", "judge_concept_alignment_pass",
    "judge_confidence",
    "judge_human_override", "judge_human_corrected_semantic",
    "judge_human_corrected_aesthetic", "judge_human_corrected_professional",
    "judge_human_reviewer", "judge_human_review_timestamp", "judge_human_note",
    "model_latency_ms", "execution_latency_ms",
    "model_cost_usd", "judge_cost_usd",
    "screenshot_path", "scene_stats_path", "is_honeypot",
]

JUDGE_VS_HUMAN_FIELDS = [
    "event_timestamp_utc", "run_id", "case_id", "attempt_index",
    "judge_model", "judge_judged_under_standard",
    "judge_semantic", "judge_aesthetic", "judge_professional",
    "human_corrected_semantic", "human_corrected_aesthetic", "human_corrected_professional",
    "delta_semantic", "delta_aesthetic", "delta_professional",
    "human_reviewer", "human_note", "screenshot_path", "prompt_used",
    "case_style_intent_explicit",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_csv(path: Path, fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
            writer.writeheader()


def _append_row(path: Path, fields: List[str], row: Dict[str, Any]) -> None:
    _ensure_csv(path, fields)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writerow(row)


def _read_all(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_all(path: Path, fields: List[str], rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _git_commit() -> str:
    try:
        import subprocess  # noqa: PLC0415
        result = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def append_run(
    run: BenchmarkRun,
    judge_model: str = "",
    cli_args: Optional[Dict[str, Any]] = None,
    notes: str = "",
) -> None:
    """Append one row to runs.csv."""
    m = run.metrics
    cfg = run.config

    row: Dict[str, Any] = {
        "run_id": run.run_id,
        "run_group_id": run.run_group_id,
        "timestamp_utc": run.timestamp_utc,
        "model_id": run.model_id,
        "judge_model": judge_model,
        "system_prompt_version": cfg.system_prompt_version,
        "prompt_template_version": run.prompt_template_version,
        "temperature": cfg.temperature,
        "seed": cfg.seed,
        "pass_at_k": cfg.pass_at_k,
        "total_cases": m.total_cases,
        "total_attempts": m.total_attempts,
        "difficulty_dist": json.dumps(m.difficulty_dist),
        "category_dist": json.dumps(m.category_dist),
        "execution_success_rate": round(m.execution_success_rate, 4),
        "hard_pass_rate": round(m.hard_pass_rate, 4),
        "topology_pass_rate": round(m.topology_pass_rate, 4),
        "avg_soft_score": round(m.avg_soft_score, 4),
        "pass_at_1": round(m.pass_at_1, 4),
        "pass_at_3": round(m.pass_at_3, 4),
        "avg_judge_semantic": m.avg_judge_semantic if m.avg_judge_semantic is not None else "",
        "avg_judge_aesthetic": m.avg_judge_aesthetic if m.avg_judge_aesthetic is not None else "",
        "avg_judge_professional": m.avg_judge_professional if m.avg_judge_professional is not None else "",
        "judge_reliable": m.judge_reliable,
        "judge_honeypot_catch_rate": m.judge_honeypot_catch_rate if m.judge_honeypot_catch_rate is not None else "",
        "judge_calibration_drift": "",
        "avg_model_latency_ms": round(m.avg_model_latency_ms, 1),
        "avg_execution_latency_ms": round(m.avg_execution_latency_ms, 1),
        "total_cost_usd": round(m.total_cost_usd, 4),
        "total_duration_s": round(m.total_duration_s, 1),
        "report_md_path": run.report_md_path,
        "report_json_path": run.report_json_path,
        "git_commit": run.git_commit or _git_commit(),
        "cli_args": json.dumps(cli_args) if cli_args else "",
        "notes": notes,
    }
    _append_row(_RUNS_CSV, RUNS_FIELDS, row)
    logger.info("Appended run %s to %s", run.run_id, _RUNS_CSV)


def append_attempt(
    run_id: str,
    attempt: AttemptArtifact,
    case: TestCaseCard,
    judge_cost_usd: float = 0.0,
) -> None:
    """Append one row to attempts.csv."""
    snap = attempt.scene_snapshot
    jr = attempt.judge_result

    row: Dict[str, Any] = {
        "run_id": run_id,
        "case_id": attempt.case_id,
        "attempt_index": attempt.attempt_index,
        "model_id": attempt.model_id,
        "category": case.category.value,
        "difficulty": case.difficulty.value,
        "task_family": case.task_family.value,
        "prompt_used": attempt.prompt_used,
        "parse_success": attempt.parse_success,
        "safety_success": attempt.safety_success,
        "execution_success": attempt.execution_success,
        "passed_hard_constraints": attempt.passed_hard_constraints,
        "passed_topology": attempt.passed_topology,
        "pass_overall": attempt.pass_overall,
        "soft_score": round(attempt.soft_score, 4),
        "failure_class": attempt.failure_class.value,
        "failure_reason": attempt.failure_reason or "",
        "total_objects": snap.total_objects,
        "total_mesh_objects": snap.total_mesh_objects,
        "total_vertices": snap.total_vertices,
        "total_faces": snap.total_faces,
        "quad_ratio": round(snap.quad_ratio, 4),
        "manifold": snap.manifold,
        "bbox_min_x": round(snap.bbox_min[0], 4),
        "bbox_min_y": round(snap.bbox_min[1], 4),
        "bbox_min_z": round(snap.bbox_min[2], 4),
        "bbox_max_x": round(snap.bbox_max[0], 4),
        "bbox_max_y": round(snap.bbox_max[1], 4),
        "bbox_max_z": round(snap.bbox_max[2], 4),
        "judge_semantic": round(jr.semantic, 3) if jr else "",
        "judge_aesthetic": round(jr.aesthetic, 3) if jr else "",
        "judge_professional": round(jr.professional, 3) if jr else "",
        "judge_stddev": round(jr.stddev, 3) if jr else "",
        "judge_judged_under_standard": jr.judged_under_standard if jr else "",
        "judge_detected_style": jr.detected_style if jr else "",
        "judge_detected_concept": jr.detected_concept if jr else "",
        "judge_style_alignment_pass": jr.style_alignment_pass if jr else "",
        "judge_concept_alignment_pass": jr.concept_alignment_pass if jr else "",
        "judge_confidence": round(jr.confidence, 3) if jr else "",
        "judge_human_override": "",
        "judge_human_corrected_semantic": "",
        "judge_human_corrected_aesthetic": "",
        "judge_human_corrected_professional": "",
        "judge_human_reviewer": "",
        "judge_human_review_timestamp": "",
        "judge_human_note": "",
        "model_latency_ms": round(attempt.model_latency_ms, 1),
        "execution_latency_ms": round(attempt.execution_latency_ms, 1),
        "model_cost_usd": round(attempt.cost_usd, 6),
        "judge_cost_usd": round(judge_cost_usd, 6),
        "screenshot_path": attempt.screenshot_path,
        "scene_stats_path": attempt.scene_stats_path,
        "is_honeypot": attempt.is_honeypot,
    }
    _append_row(_ATTEMPTS_CSV, ATTEMPTS_FIELDS, row)


def update_human_review(
    run_id: str,
    case_id: str,
    attempt_index: int,
    override: str,
    corrected_semantic: Optional[float],
    corrected_aesthetic: Optional[float],
    corrected_professional: Optional[float],
    reviewer: str,
    timestamp_utc: str,
    note: str = "",
) -> None:
    """In-place update of judge_human_* fields in attempts.csv."""
    rows = _read_all(_ATTEMPTS_CSV)
    updated = False
    for row in rows:
        if (
            row.get("run_id") == run_id
            and row.get("case_id") == case_id
            and str(row.get("attempt_index")) == str(attempt_index)
        ):
            row["judge_human_override"] = override
            row["judge_human_corrected_semantic"] = corrected_semantic if corrected_semantic is not None else ""
            row["judge_human_corrected_aesthetic"] = corrected_aesthetic if corrected_aesthetic is not None else ""
            row["judge_human_corrected_professional"] = corrected_professional if corrected_professional is not None else ""
            row["judge_human_reviewer"] = reviewer
            row["judge_human_review_timestamp"] = timestamp_utc
            row["judge_human_note"] = note
            updated = True
            break

    if updated:
        _write_all(_ATTEMPTS_CSV, ATTEMPTS_FIELDS, rows)
        logger.info("Updated human review for %s/%s attempt %d", run_id, case_id, attempt_index)
    else:
        logger.warning("No matching row for human review update: %s/%s %d", run_id, case_id, attempt_index)


def append_judge_vs_human(
    event: Dict[str, Any],
) -> None:
    """Append a judge-vs-human disagreement event."""
    _append_row(_JUDGE_VS_HUMAN_CSV, JUDGE_VS_HUMAN_FIELDS, event)


def query_runs(model_id: Optional[str] = None, last_n: Optional[int] = None) -> List[Dict[str, str]]:
    rows = _read_all(_RUNS_CSV)
    if model_id:
        rows = [r for r in rows if r.get("model_id") == model_id]
    if last_n:
        rows = rows[-last_n:]
    return rows


def query_attempts(run_id: Optional[str] = None, case_id: Optional[str] = None) -> List[Dict[str, str]]:
    rows = _read_all(_ATTEMPTS_CSV)
    if run_id:
        rows = [r for r in rows if r.get("run_id") == run_id]
    if case_id:
        rows = [r for r in rows if r.get("case_id") == case_id]
    return rows
