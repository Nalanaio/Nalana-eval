"""Query and display benchmark run history from db/runs.csv."""
from __future__ import annotations

from typing import Dict, List, Optional

from nalana_eval import csv_db

_BLOCKS = "▁▂▃▄▅▆▇█"


def _sparkline(values: List[float], width: int = 30) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = hi - lo or 1.0
    chars = [_BLOCKS[int((v - lo) / span * (len(_BLOCKS) - 1))] for v in values[-width:]]
    return "".join(chars)


def _fmt(v: str, width: int = 8) -> str:
    return str(v)[:width].ljust(width)


def _table(rows: List[Dict[str, str]], cols: List[str]) -> str:
    widths = {c: max(len(c), *(len(r.get(c, "")) for r in rows)) for c in cols}
    sep = "  ".join("-" * widths[c] for c in cols)
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    lines = [header, sep]
    for row in rows:
        lines.append("  ".join((row.get(c, "") or "").ljust(widths[c]) for c in cols))
    return "\n".join(lines)


def show(
    model_id: str = "",
    last_n: int = 10,
    compare_models: Optional[List[str]] = None,
    case_id: str = "",
) -> None:
    if case_id:
        _show_case(case_id, model_id)
        return
    if compare_models:
        _show_compare(compare_models, last_n)
        return
    _show_runs(model_id, last_n)


def _show_runs(model_id: str, last_n: int) -> None:
    rows = csv_db.query_runs(model_id=model_id or None, last_n=last_n)
    if not rows:
        print("No runs found.")
        return

    cols = ["run_id", "timestamp_utc", "model_id", "total_cases",
            "hard_pass_rate", "topology_pass_rate", "pass_at_3", "total_cost_usd"]
    print(_table(rows, cols))

    # Sparkline of hard_pass_rate over time
    rates = []
    for r in rows:
        try:
            rates.append(float(r.get("hard_pass_rate", 0) or 0))
        except ValueError:
            pass
    if rates:
        label = f"{'hard_pass_rate trend':>22}"
        print(f"\n{label}  {_sparkline(rates)}")
        print(f"{'min=':>22}  {min(rates):.3f}  max={max(rates):.3f}")


def _show_compare(models: List[str], last_n: int) -> None:
    print(f"Comparing: {', '.join(models)}\n")
    cols = ["model_id", "runs", "avg_hard_pass", "avg_pass_at_3", "avg_cost_usd"]
    summary_rows: List[Dict[str, str]] = []

    for mid in models:
        rows = csv_db.query_runs(model_id=mid, last_n=last_n)
        if not rows:
            summary_rows.append({"model_id": mid, "runs": "0", "avg_hard_pass": "N/A",
                                  "avg_pass_at_3": "N/A", "avg_cost_usd": "N/A"})
            continue

        def _avg(field: str) -> float:
            vals = [float(r.get(field) or 0) for r in rows if r.get(field)]
            return sum(vals) / len(vals) if vals else 0.0

        summary_rows.append({
            "model_id": mid,
            "runs": str(len(rows)),
            "avg_hard_pass": f"{_avg('hard_pass_rate'):.3f}",
            "avg_pass_at_3": f"{_avg('pass_at_3'):.3f}",
            "avg_cost_usd": f"{_avg('total_cost_usd'):.4f}",
        })

    print(_table(summary_rows, cols))


def _show_case(case_id: str, model_id: str) -> None:
    attempts = csv_db.query_attempts(case_id=case_id)
    if model_id:
        attempts = [a for a in attempts if a.get("model_id") == model_id]
    if not attempts:
        print(f"No attempts found for case {case_id!r}.")
        return

    cols = ["run_id", "attempt_index", "model_id", "pass_overall",
            "failure_class", "soft_score", "judge_semantic"]
    print(f"Case: {case_id}\n")
    print(_table(attempts, cols))
