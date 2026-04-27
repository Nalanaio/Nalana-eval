"""Generate benchmark run reports: report.md and report.json."""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from nalana_eval.schema import AttemptArtifact, BenchmarkRun, FailureClass

logger = logging.getLogger(__name__)

_PASS_ICON = "✅"
_FAIL_ICON = "❌"
_WARN_ICON = "⚠️"


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _score(value: Optional[float]) -> str:
    return f"{value:.2f}" if value is not None else "N/A"


def _pass_icon(passed: bool) -> str:
    return _PASS_ICON if passed else _FAIL_ICON


def _render_summary_table(runs: List[BenchmarkRun]) -> str:
    header = "| Model | Hard Pass | Topology Pass | Avg Soft | Pass@1 | Pass@3 | Judge Avg |"
    sep = "|---|---|---|---|---|---|---|"
    rows = [header, sep]
    for run in runs:
        m = run.metrics
        judge_avg = ""
        if m.avg_judge_semantic is not None:
            j = (m.avg_judge_semantic + (m.avg_judge_aesthetic or 0) + (m.avg_judge_professional or 0)) / 3
            judge_avg = f"{j:.2f}/5"
        rows.append(
            f"| {run.model_id} "
            f"| {_pct(m.hard_pass_rate)} "
            f"| {_pct(m.topology_pass_rate)} "
            f"| {_score(m.avg_soft_score)} "
            f"| {_pct(m.pass_at_1)} "
            f"| {_pct(m.pass_at_3)} "
            f"| {judge_avg or 'N/A'} |"
        )
    return "\n".join(rows)


def _render_failure_summary(attempts: List[AttemptArtifact]) -> str:
    counts: Counter[str] = Counter()
    for a in attempts:
        if not a.pass_overall:
            counts[a.failure_class.value] += 1
    if not counts:
        return "_No failures._"
    lines = []
    for i, (cls, cnt) in enumerate(counts.most_common(), start=1):
        lines.append(f"{i}. `{cls}` — {cnt} attempt(s)")
    return "\n".join(lines)


def _render_attempt_block(attempt: AttemptArtifact, run_output_dir: Path) -> str:
    icon = _pass_icon(attempt.pass_overall)
    case_id = attempt.case_id
    idx = attempt.attempt_index

    # Screenshot as relative path
    screenshot_rel = ""
    if attempt.screenshot_path:
        sp = Path(attempt.screenshot_path)
        thumb = sp.parent / (sp.stem + "_thumb" + sp.suffix)
        thumb_rel = thumb.name if thumb.exists() else sp.name
        screenshot_rel = f"[![attempt {idx}](screenshots/{thumb_rel})](screenshots/{sp.name})"

    lines = [
        f"### {icon} `{case_id}` — attempt {idx}",
        "",
        f"**Model**: {attempt.model_id}  ",
        f"**Prompt**: {attempt.prompt_used[:120]}{'...' if len(attempt.prompt_used) > 120 else ''}",
        "",
    ]

    if screenshot_rel:
        lines += [screenshot_rel, ""]

    # Hard constraints
    hc_status = _pass_icon(attempt.passed_hard_constraints)
    lines.append(f"**Hard constraints**: {hc_status}")

    # Topology
    tp_status = _pass_icon(attempt.passed_topology)
    snap = attempt.scene_snapshot
    lines.append(
        f"**Topology**: {tp_status} "
        f"manifold={snap.manifold}, quad_ratio={snap.quad_ratio:.2f}, "
        f"faces={snap.total_faces}"
    )

    # Soft score
    lines.append(f"**Soft score**: {attempt.soft_score:.3f}")

    # Judge
    jr = attempt.judge_result
    if jr:
        lines.append(
            f"**Judge** (under \"{jr.judged_under_standard}\"): "
            f"semantic={jr.semantic:.1f} aesthetic={jr.aesthetic:.1f} "
            f"professional={jr.professional:.1f} stddev={jr.stddev:.2f}"
        )
        lines.append(f"  _Reasoning_: {jr.reasoning[:200]}")
    elif attempt.pass_overall is False:
        lines.append(f"**Failure**: `{attempt.failure_class.value}` — {attempt.failure_reason or ''}")

    # HUMAN_REVIEW_BLOCK
    lines += [
        "",
        f"<!-- HUMAN_REVIEW_BLOCK:{case_id}:attempt_{idx}",
        "override: pending",
        "corrected_semantic:",
        "corrected_aesthetic:",
        "corrected_professional:",
        "reviewer:",
        "note:",
        "END_HUMAN_REVIEW_BLOCK -->",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate(
    runs: List[BenchmarkRun],
    output_dir: Path,
    run_group_id: str = "",
) -> None:
    """Write report.md and report.json into output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if not runs:
        logger.warning("No runs to report")
        return

    primary_run = runs[0]
    total_cases = primary_run.metrics.total_cases
    total_attempts = sum(r.metrics.total_attempts for r in runs)
    model_list = ", ".join(r.model_id for r in runs)

    md_lines: List[str] = [
        "# Nalana Benchmark Run Report",
        "",
        f"**Run Group**: {run_group_id or primary_run.run_group_id}  ",
        f"**Models**: {model_list}  ",
        f"**Total Cases**: {total_cases} | **Total Attempts**: {total_attempts}  ",
        f"**Timestamp**: {primary_run.timestamp_utc}",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        _render_summary_table(runs),
        "",
        "---",
        "",
    ]

    # Failure breakdown per model
    for run in runs:
        md_lines += [
            f"## Top Failure Reasons — {run.model_id}",
            "",
            _render_failure_summary(run.attempts),
            "",
        ]

    md_lines += ["---", "", "## Sample Cases", ""]

    # Show all failures + some passes (up to 20 total)
    for run in runs:
        failures = [a for a in run.attempts if not a.pass_overall]
        passes = [a for a in run.attempts if a.pass_overall]
        samples = failures[:15] + passes[:5]

        for attempt in samples:
            md_lines.append(_render_attempt_block(attempt, output_dir))
            md_lines.append("")

    report_md = "\n".join(md_lines)
    md_path = output_dir / "report.md"
    md_path.write_text(report_md, encoding="utf-8")
    logger.info("Wrote %s", md_path)

    # JSON report
    json_path = output_dir / "report.json"
    report_data: Dict[str, Any] = {
        "run_group_id": run_group_id or primary_run.run_group_id,
        "runs": [r.model_dump(mode="json") for r in runs],
    }
    json_path.write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Wrote %s", json_path)

    # Update run objects with paths
    for run in runs:
        run.report_md_path = str(md_path)
        run.report_json_path = str(json_path)
