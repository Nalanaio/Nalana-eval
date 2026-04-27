"""Unit tests for judge.py — mocks all provider API calls."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from nalana_eval.judge import (
    Judge,
    _build_style_intent_block,
    _median,
    _parse_raw_response,
    _stddev,
)
from nalana_eval.schema import (
    ArtifactPolicy,
    Category,
    Difficulty,
    HardConstraints,
    InitialScene,
    JudgePolicy,
    StyleIntent,
    TaskFamily,
    TestCaseCard,
    TopologyPolicy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_RESPONSE = json.dumps({
    "detected_style": "geometric",
    "detected_concept": "cube",
    "style_alignment_pass": True,
    "concept_alignment_pass": True,
    "judged_under_standard": "geometric",
    "scores_within_detected_style": {
        "concept_recognizability": 4.0,
        "style_execution": 3.5,
        "geometric_quality": 4.5,
    },
    "reasoning": "Solid geometry.",
    "confidence": 0.8,
})


def _make_case(
    judge_policy: JudgePolicy = JudgePolicy.SCORE,
    style_intent: StyleIntent | None = None,
) -> TestCaseCard:
    return TestCaseCard(
        id="TEST-J001",
        category=Category.OBJECT_CREATION,
        difficulty=Difficulty.SHORT,
        task_family=TaskFamily.PRIMITIVE_CREATION,
        prompt_variants=["Add a cube"],
        initial_scene=InitialScene(),
        hard_constraints=HardConstraints(),
        topology_policy=TopologyPolicy(),
        soft_constraints=[],
        style_intent=style_intent or StyleIntent(),
        judge_policy=judge_policy,
        artifact_policy=ArtifactPolicy(),
    )


# ---------------------------------------------------------------------------
# _parse_raw_response
# ---------------------------------------------------------------------------


def test_parse_raw_response_extracts_all_fields():
    result = _parse_raw_response(_VALID_RESPONSE)
    assert result["semantic"] == pytest.approx(4.0)
    assert result["aesthetic"] == pytest.approx(3.5)
    assert result["professional"] == pytest.approx(4.5)
    assert result["detected_style"] == "geometric"
    assert result["style_alignment_pass"] is True


def test_parse_raw_response_clamps_to_bounds():
    raw = json.dumps({
        "detected_style": "realistic",
        "detected_concept": None,
        "style_alignment_pass": False,
        "concept_alignment_pass": True,
        "judged_under_standard": "realistic",
        "scores_within_detected_style": {
            "concept_recognizability": 10.0,
            "style_execution": 0.5,
            "geometric_quality": 6.0,
        },
        "reasoning": "",
        "confidence": 0.5,
    })
    result = _parse_raw_response(raw)
    assert result["semantic"] == pytest.approx(5.0)
    assert result["aesthetic"] == pytest.approx(1.0)  # clamped from 0.5
    assert result["professional"] == pytest.approx(5.0)  # clamped from 6.0


def test_parse_raw_response_no_concept_falls_back_to_style_exec():
    raw = json.dumps({
        "detected_style": "low-poly",
        "detected_concept": None,
        "style_alignment_pass": True,
        "concept_alignment_pass": True,
        "judged_under_standard": "low-poly",
        "scores_within_detected_style": {
            "concept_recognizability": None,
            "style_execution": 3.0,
            "geometric_quality": 4.0,
        },
        "reasoning": "",
        "confidence": 0.7,
    })
    result = _parse_raw_response(raw)
    assert result["semantic"] == pytest.approx(3.0)


def test_parse_raw_response_embedded_json():
    raw = 'Some preamble\n{"detected_style":"geometric","detected_concept":"cube","style_alignment_pass":true,"concept_alignment_pass":true,"judged_under_standard":"geometric","scores_within_detected_style":{"concept_recognizability":3.0,"style_execution":3.0,"geometric_quality":3.0},"reasoning":"ok","confidence":0.5}'
    result = _parse_raw_response(raw)
    assert result["semantic"] == pytest.approx(3.0)


def test_parse_raw_response_invalid_raises():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_raw_response("not json at all, no braces")


# ---------------------------------------------------------------------------
# _median / _stddev
# ---------------------------------------------------------------------------


def test_median_odd():
    assert _median([1.0, 5.0, 3.0]) == pytest.approx(3.0)


def test_median_even():
    assert _median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)


def test_median_single():
    assert _median([4.2]) == pytest.approx(4.2)


def test_stddev_uniform():
    assert _stddev([3.0, 3.0, 3.0]) == pytest.approx(0.0)


def test_stddev_nonzero():
    sd = _stddev([1.0, 3.0, 5.0])
    assert sd > 0.0


# ---------------------------------------------------------------------------
# _build_style_intent_block
# ---------------------------------------------------------------------------


def test_style_intent_block_explicit():
    si = StyleIntent(explicit=True, style="cartoon", concept="apple")
    block = _build_style_intent_block(si)
    assert "explicit: true" in block
    assert "cartoon" in block
    assert "MUST match" in block


def test_style_intent_block_open_with_styles():
    si = StyleIntent(explicit=False, acceptable_styles=["geometric", "low-poly"])
    block = _build_style_intent_block(si)
    assert "explicit: false" in block
    assert "geometric" in block
    assert "left style open" in block.lower()


def test_style_intent_block_fully_open():
    si = StyleIntent()
    block = _build_style_intent_block(si)
    assert "no style restrictions" in block


# ---------------------------------------------------------------------------
# Judge.judge — skip policy
# ---------------------------------------------------------------------------


def test_judge_skips_when_policy_skip(tmp_path):
    case = _make_case(judge_policy=JudgePolicy.SKIP)
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG")
    j = Judge(judge_model="gpt-4o", api_key="fake", db_path=tmp_path / "cache.sqlite")
    result = j.judge(case, "Add a cube", str(png))
    assert result is None


def test_judge_skips_when_no_screenshot(tmp_path):
    case = _make_case()
    j = Judge(judge_model="gpt-4o", api_key="fake", db_path=tmp_path / "cache.sqlite")
    result = j.judge(case, "Add a cube", str(tmp_path / "nonexistent.png"))
    assert result is None


def test_judge_skips_when_budget_zero(tmp_path):
    case = _make_case()
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG")
    j = Judge(
        judge_model="gpt-4o",
        api_key="fake",
        db_path=tmp_path / "cache.sqlite",
        budget_remaining=0.0,
    )
    result = j.judge(case, "Add a cube", str(png))
    assert result is None


# ---------------------------------------------------------------------------
# Judge.judge — successful mock run
# ---------------------------------------------------------------------------


def test_judge_returns_median_of_n_runs(tmp_path):
    case = _make_case()
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG")

    db = tmp_path / "cache.sqlite"
    j = Judge(
        judge_model="gpt-4o",
        api_key="fake",
        db_path=db,
        n_runs=3,
    )

    responses = [
        json.dumps({
            "detected_style": "geometric",
            "detected_concept": "cube",
            "style_alignment_pass": True,
            "concept_alignment_pass": True,
            "judged_under_standard": "geometric",
            "scores_within_detected_style": {
                "concept_recognizability": score,
                "style_execution": score,
                "geometric_quality": score,
            },
            "reasoning": "ok",
            "confidence": 0.9,
        })
        for score in [3.0, 4.0, 5.0]
    ]

    call_count = 0

    def fake_call(user_msg, image_b64, image_bytes):
        nonlocal call_count
        resp = responses[call_count % 3]
        call_count += 1
        return resp

    j._call_once = fake_call
    result = j.judge(case, "Add a cube", str(png))

    assert result is not None
    assert result.semantic == pytest.approx(4.0)  # median of [3,4,5]


# ---------------------------------------------------------------------------
# Judge.judge — cache hit
# ---------------------------------------------------------------------------


def test_judge_cache_hit_skips_api_call(tmp_path):
    case = _make_case()
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG")
    db = tmp_path / "cache.sqlite"

    j = Judge(judge_model="gpt-4o", api_key="fake", db_path=db, n_runs=1)

    api_call_count = 0

    def fake_call(user_msg, image_b64, image_bytes):
        nonlocal api_call_count
        api_call_count += 1
        return _VALID_RESPONSE

    j._call_once = fake_call

    # First call — populates cache
    r1 = j.judge(case, "Add a cube", str(png))
    assert api_call_count == 1

    # Second call — should hit cache
    r2 = j.judge(case, "Add a cube", str(png))
    assert api_call_count == 1  # no additional API call
    assert r2 is not None
    assert r2.semantic == pytest.approx(r1.semantic)
