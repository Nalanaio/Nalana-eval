"""Parse HUMAN_REVIEW_BLOCK annotations from report.md and back-fill attempts.csv."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from nalana_eval import csv_db

_BLOCK_RE = re.compile(
    r"<!-- HUMAN_REVIEW_BLOCK:([^:]+):attempt_(\d+)\n(.*?)\nEND_HUMAN_REVIEW_BLOCK -->",
    re.DOTALL,
)

_FIELD_RE = re.compile(r"^(\w+):\s*(.*?)\s*$", re.MULTILINE)


def _parse_block(case_id: str, attempt_index: int, body: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for m in _FIELD_RE.finditer(body):
        fields[m.group(1)] = m.group(2)
    return {
        "case_id": case_id,
        "attempt_index": attempt_index,
        "override": fields.get("override", ""),
        "corrected_semantic": fields.get("corrected_semantic", ""),
        "corrected_aesthetic": fields.get("corrected_aesthetic", ""),
        "corrected_professional": fields.get("corrected_professional", ""),
        "reviewer": fields.get("reviewer", ""),
        "note": fields.get("note", ""),
    }


def _try_float(s: str) -> Optional[float]:
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _infer_run_id(report_path: Path) -> str:
    """Try to extract run_id from the report path (run_group_<id>/report.md)."""
    parts = report_path.parts
    for part in reversed(parts):
        if part.startswith("run_"):
            return part.split("_")[-1]
    return ""


def collect(report_path: str) -> None:
    p = Path(report_path)
    if not p.exists():
        print(f"Error: {report_path!r} not found", file=sys.stderr)
        sys.exit(1)

    text = p.read_text(encoding="utf-8")
    blocks = _BLOCK_RE.findall(text)

    if not blocks:
        print("No HUMAN_REVIEW_BLOCKs found.")
        return

    run_id = _infer_run_id(p)
    timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = 0
    skipped = 0

    for case_id, attempt_str, body in blocks:
        attempt_index = int(attempt_str)
        parsed = _parse_block(case_id, attempt_index, body)
        override = parsed["override"]

        if not override or override == "pending":
            skipped += 1
            continue

        csv_db.update_human_review(
            run_id=run_id,
            case_id=case_id,
            attempt_index=attempt_index,
            override=override,
            corrected_semantic=_try_float(parsed["corrected_semantic"]),
            corrected_aesthetic=_try_float(parsed["corrected_aesthetic"]),
            corrected_professional=_try_float(parsed["corrected_professional"]),
            reviewer=parsed["reviewer"],
            timestamp_utc=timestamp_utc,
            note=parsed["note"],
        )
        updated += 1

        # If reviewer disagreed, append to judge_vs_human.csv for long-term analysis
        if override == "disagree":
            attempts = csv_db.query_attempts(run_id=run_id or None, case_id=case_id)
            matching = [
                a for a in attempts
                if str(a.get("attempt_index")) == str(attempt_index)
            ]
            if matching:
                a = matching[0]
                event: Dict[str, Any] = {
                    "event_timestamp_utc": timestamp_utc,
                    "run_id": run_id,
                    "case_id": case_id,
                    "attempt_index": attempt_index,
                    "judge_model": "",
                    "judge_judged_under_standard": a.get("judge_judged_under_standard", ""),
                    "judge_semantic": a.get("judge_semantic", ""),
                    "judge_aesthetic": a.get("judge_aesthetic", ""),
                    "judge_professional": a.get("judge_professional", ""),
                    "human_corrected_semantic": parsed["corrected_semantic"],
                    "human_corrected_aesthetic": parsed["corrected_aesthetic"],
                    "human_corrected_professional": parsed["corrected_professional"],
                    "delta_semantic": _delta(a.get("judge_semantic"), parsed["corrected_semantic"]),
                    "delta_aesthetic": _delta(a.get("judge_aesthetic"), parsed["corrected_aesthetic"]),
                    "delta_professional": _delta(a.get("judge_professional"), parsed["corrected_professional"]),
                    "human_reviewer": parsed["reviewer"],
                    "human_note": parsed["note"],
                    "screenshot_path": a.get("screenshot_path", ""),
                    "prompt_used": a.get("prompt_used", ""),
                    "case_style_intent_explicit": "",
                }
                csv_db.append_judge_vs_human(event)

    print(f"Collected {updated} reviews, skipped {skipped} (pending/empty).")


def _delta(judge_val: str, human_val: str) -> str:
    try:
        return str(float(human_val) - float(judge_val))
    except (ValueError, TypeError):
        return ""
