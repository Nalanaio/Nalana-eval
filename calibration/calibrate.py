"""Judge calibration: score reference images to detect systematic bias.

Usage:
    python -m nalana_eval.cli calibrate --judge-model gpt-4o
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _fake_case(style: str, concept: str) -> "object":
    """Build a minimal TestCaseCard for calibration (no hard constraints)."""
    from nalana_eval.schema import (  # noqa: PLC0415
        ArtifactPolicy, Category, Difficulty, HardConstraints, InitialScene,
        JudgePolicy, StyleIntent, TaskFamily, TestCaseCard, TopologyPolicy,
    )
    return TestCaseCard(
        id=f"CALIB_{style}_{concept}",
        category=Category.OBJECT_CREATION,
        difficulty=Difficulty.SHORT,
        task_family=TaskFamily.OPEN_ENDED_CREATIVE,
        prompt_variants=[f"Create a {concept}"],
        initial_scene=InitialScene(),
        hard_constraints=HardConstraints(),
        topology_policy=TopologyPolicy(),
        style_intent=StyleIntent(
            explicit=True,
            style=style,
            concept=concept,
        ),
        judge_policy=JudgePolicy.SCORE,
        artifact_policy=ArtifactPolicy(require_screenshot=False),
    )


def _stddev(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def run(
    judge_model: str = "gpt-4o",
    reference_dir: str = "calibration/reference_images",
    output_dir: str = "calibration/baseline_results",
) -> None:
    from nalana_eval.judge import Judge  # noqa: PLC0415

    ref_path = Path(reference_dir)
    if not ref_path.exists():
        logger.warning("Reference dir %s not found — calibration skipped", ref_path)
        return

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    judge = Judge(judge_model=judge_model, budget_remaining=50.0)

    # ref_path/<style>/<image>.png
    style_results: Dict[str, List[Dict[str, Any]]] = {}

    for style_dir in sorted(ref_path.iterdir()):
        if not style_dir.is_dir():
            continue
        style = style_dir.name
        images = sorted(style_dir.glob("*.png"))
        if not images:
            continue

        logger.info("Calibrating style %r with %d images", style, len(images))
        style_results[style] = []

        for img in images:
            concept = img.stem.replace("_", " ")
            case = _fake_case(style, concept)
            try:
                result = judge.judge(case, f"Create a {concept}", str(img))
                if result:
                    style_results[style].append({
                        "image": img.name,
                        "concept": concept,
                        "semantic": result.semantic,
                        "aesthetic": result.aesthetic,
                        "professional": result.professional,
                        "style_alignment_pass": result.style_alignment_pass,
                        "judged_under_standard": result.judged_under_standard,
                        "confidence": result.confidence,
                    })
            except Exception as exc:
                logger.warning("Judge failed for %s/%s: %s", style, img.name, exc)

    # Aggregate
    report: Dict[str, Any] = {
        "judge_model": judge_model,
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "styles": {},
    }

    for style, results in style_results.items():
        if not results:
            continue
        semantics = [r["semantic"] for r in results]
        aesthetics = [r["aesthetic"] for r in results]
        professionals = [r["professional"] for r in results]
        report["styles"][style] = {
            "n_images": len(results),
            "avg_semantic": round(sum(semantics) / len(semantics), 3),
            "avg_aesthetic": round(sum(aesthetics) / len(aesthetics), 3),
            "avg_professional": round(sum(professionals) / len(professionals), 3),
            "stddev_semantic": round(_stddev(semantics), 3),
            "results": results,
        }

    # Cross-style bias check
    if len(report["styles"]) >= 2:
        all_avg = [v["avg_semantic"] for v in report["styles"].values()]
        report["cross_style_semantic_stddev"] = round(_stddev(all_avg), 3)
        report["bias_flag"] = _stddev(all_avg) > 0.3

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = out_path / f"{judge_model.replace('/', '_')}_{ts}.json"
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Calibration report written to %s", out_file)

    # Print summary
    print(f"\nCalibration summary — {judge_model}")
    print(f"{'Style':<20} {'avg_sem':>8} {'avg_aes':>8} {'avg_pro':>8} {'n':>4}")
    print("-" * 54)
    for style, data in report["styles"].items():
        print(
            f"{style:<20} {data['avg_semantic']:>8.3f} "
            f"{data['avg_aesthetic']:>8.3f} {data['avg_professional']:>8.3f} "
            f"{data['n_images']:>4}"
        )
    if "cross_style_semantic_stddev" in report:
        flag = "  ⚠️  BIAS" if report.get("bias_flag") else ""
        print(f"\nCross-style semantic stddev: {report['cross_style_semantic_stddev']:.3f}{flag}")
