"""Tests for nalana_eval/schema.py (v3.0)."""
from __future__ import annotations

import json
import pytest
from pydantic import ValidationError

from nalana_eval.schema import (
    ArtifactPolicy,
    AttemptArtifact,
    BoundingBoxConstraint,
    BoundingBoxSizeRange,
    Category,
    CountRange,
    Difficulty,
    FailureClass,
    HardConstraints,
    InitialScene,
    JudgePolicy,
    JudgeResult,
    MaterialConstraint,
    NormalizedStep,
    Provenance,
    SceneComplexity,
    SceneMeshSnapshot,
    SceneSnapshot,
    SceneSeed,
    SoftConstraint,
    SoftDirection,
    SoftMetric,
    StepKind,
    StyleIntent,
    Tag,
    TaskFamily,
    TestCaseCard,
    TestSuite,
    TopologyPolicy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_case(**overrides) -> dict:
    base = {
        "id": "CV-OBJ-0001",
        "category": "Object Creation",
        "difficulty": "Short",
        "task_family": "primitive_creation",
        "prompt_variants": ["创建一个立方体", "Add a cube"],
        "hard_constraints": {"mesh_object_count": {"minimum": 1}},
        "topology_policy": {"manifold_required": False},
        "style_intent": {"explicit": False, "concept": "cube", "acceptable_styles": ["geometric"]},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Enum smoke tests
# ---------------------------------------------------------------------------

def test_category_values():
    assert Category.OBJECT_CREATION == "Object Creation"
    assert Category.ERROR_RECOVERY == "Error Recovery & Safety"


def test_difficulty_values():
    assert Difficulty.SHORT == "Short"
    assert Difficulty.LONG == "Long"


def test_task_family_values():
    assert TaskFamily.PRIMITIVE_CREATION == "primitive_creation"
    assert TaskFamily.OPEN_ENDED_CREATIVE == "open_ended_creative"


def test_judge_policy_values():
    assert JudgePolicy.SKIP == "skip"
    assert JudgePolicy.SCORE == "score"
    assert JudgePolicy.AUDIT_ONLY == "audit_only"


def test_failure_class_v3_has_constraint_failed():
    assert FailureClass.CONSTRAINT_FAILED == "CONSTRAINT_FAILED"
    assert FailureClass.TOPOLOGY_FAILED == "TOPOLOGY_FAILED"
    assert FailureClass.WORKER_TIMEOUT == "WORKER_TIMEOUT"


# ---------------------------------------------------------------------------
# CountRange
# ---------------------------------------------------------------------------

def test_count_range_matches():
    cr = CountRange(minimum=1, maximum=3)
    assert cr.matches(1)
    assert cr.matches(3)
    assert not cr.matches(0)
    assert not cr.matches(4)


def test_count_range_no_upper():
    cr = CountRange(minimum=2)
    assert cr.matches(100)
    assert not cr.matches(1)


def test_count_range_invalid():
    with pytest.raises(ValidationError):
        CountRange(minimum=5, maximum=3)


# ---------------------------------------------------------------------------
# StyleIntent
# ---------------------------------------------------------------------------

def test_style_intent_explicit_requires_style():
    with pytest.raises(ValidationError):
        StyleIntent(explicit=True)  # style missing


def test_style_intent_explicit_ok():
    si = StyleIntent(explicit=True, style="cartoon", concept="apple")
    assert si.style == "cartoon"


def test_style_intent_implicit():
    si = StyleIntent(explicit=False, concept="sphere", acceptable_styles=["geometric"])
    assert not si.explicit
    assert "geometric" in si.acceptable_styles


# ---------------------------------------------------------------------------
# InitialScene
# ---------------------------------------------------------------------------

def test_initial_scene_mode_normalized():
    scene = InitialScene(mode="object")
    assert scene.mode == "OBJECT"


def test_initial_scene_with_seed():
    scene = InitialScene(
        mode="OBJECT",
        objects=[{"primitive": "cube", "name": "MyCube"}],
    )
    assert scene.objects[0].primitive == "CUBE"


def test_initial_scene_active_alias():
    scene = InitialScene.model_validate({"mode": "OBJECT", "active": "Cube"})
    assert scene.active_object == "Cube"


# ---------------------------------------------------------------------------
# HardConstraints
# ---------------------------------------------------------------------------

def test_hard_constraints_empty_is_valid():
    hc = HardConstraints()
    assert hc.mesh_object_count is None
    assert hc.materials == []


def test_hard_constraints_bbox():
    hc = HardConstraints(
        bounding_boxes=[
            {"target": "__scene__", "size_range": {"minimum": [1.0, 1.0, 1.0], "maximum": [5.0, 5.0, 5.0]}}
        ]
    )
    assert len(hc.bounding_boxes) == 1
    assert hc.bounding_boxes[0].target == "__scene__"


def test_material_constraint_color_validated():
    with pytest.raises(ValidationError):
        MaterialConstraint(target="*", base_color=[1.5, 0.0, 0.0])  # out of range


def test_material_constraint_ok():
    mc = MaterialConstraint(target="*", base_color=[1.0, 0.0, 0.0, 1.0], tolerance=0.2)
    assert mc.base_color[0] == 1.0


# ---------------------------------------------------------------------------
# TopologyPolicy
# ---------------------------------------------------------------------------

def test_topology_policy_defaults():
    tp = TopologyPolicy()
    assert not tp.manifold_required
    assert tp.quad_ratio_min == 0.0
    assert tp.max_face_count is None


def test_topology_policy_invalid_quad_ratio():
    with pytest.raises(ValidationError):
        TopologyPolicy(quad_ratio_min=1.5)


# ---------------------------------------------------------------------------
# SoftConstraint
# ---------------------------------------------------------------------------

def test_soft_constraint_ok():
    sc = SoftConstraint(name="顶点数", metric="total_vertices", direction="min", target=100.0, weight=0.5)
    assert sc.metric == SoftMetric.TOTAL_VERTICES
    assert sc.direction == SoftDirection.MIN


def test_soft_constraint_zero_weight_invalid():
    with pytest.raises(ValidationError):
        SoftConstraint(name="x", metric="total_faces", direction="max", target=500.0, weight=0.0)


# ---------------------------------------------------------------------------
# TestCaseCard
# ---------------------------------------------------------------------------

def test_test_case_card_minimal():
    case = TestCaseCard.model_validate(_minimal_case())
    assert case.id == "CV-OBJ-0001"
    assert case.fixture_version == "3.0"
    assert case.judge_policy == JudgePolicy.SCORE


def test_test_case_card_empty_prompt_variants_rejected():
    with pytest.raises(ValidationError):
        TestCaseCard.model_validate(_minimal_case(prompt_variants=[]))


def test_test_case_card_whitespace_prompts_trimmed():
    case = TestCaseCard.model_validate(_minimal_case(prompt_variants=["  cube  ", "box"]))
    assert case.prompt_variants[0] == "cube"


def test_test_case_card_unknown_field_rejected():
    with pytest.raises(ValidationError):
        TestCaseCard.model_validate(_minimal_case(unknown_field="bad"))


def test_test_case_card_judge_policy_skip():
    case = TestCaseCard.model_validate(_minimal_case(judge_policy="skip"))
    assert case.judge_policy == JudgePolicy.SKIP


# ---------------------------------------------------------------------------
# ADR-005: SceneComplexity / Provenance / Tag / draft / deprecated Difficulty
# ---------------------------------------------------------------------------


def test_scene_complexity_default_is_single_object():
    """If a fixture omits scene_complexity, it defaults to SINGLE_OBJECT.
    This is the safe default used for mechanical backfill in #15.1; #15.2 fixes wrong tags."""
    case = TestCaseCard.model_validate(_minimal_case())
    assert case.scene_complexity == SceneComplexity.SINGLE_OBJECT


def test_scene_complexity_explicit_value():
    case = TestCaseCard.model_validate(_minimal_case(scene_complexity="composition"))
    assert case.scene_complexity == SceneComplexity.COMPOSITION


def test_scene_complexity_invalid_value_rejected():
    with pytest.raises(ValidationError):
        TestCaseCard.model_validate(_minimal_case(scene_complexity="not_a_real_value"))


def test_provenance_default_is_handcrafted():
    case = TestCaseCard.model_validate(_minimal_case())
    assert case.provenance == Provenance.HANDCRAFTED


def test_provenance_synthetic():
    case = TestCaseCard.model_validate(_minimal_case(provenance="synthetic"))
    assert case.provenance == Provenance.SYNTHETIC


def test_provenance_llm_authored():
    case = TestCaseCard.model_validate(_minimal_case(provenance="llm_authored"))
    assert case.provenance == Provenance.LLM_AUTHORED


def test_tags_default_is_empty_list():
    """Default empty list — fixtures get backfilled with ['canonical'] by #15.1 script."""
    case = TestCaseCard.model_validate(_minimal_case())
    assert case.tags == []


def test_tags_canonical_explicit():
    case = TestCaseCard.model_validate(_minimal_case(tags=["canonical"]))
    assert Tag.CANONICAL in case.tags


def test_tags_multiple():
    case = TestCaseCard.model_validate(_minimal_case(tags=["canonical", "adversarial"]))
    assert set(case.tags) == {Tag.CANONICAL, Tag.ADVERSARIAL}


def test_tags_invalid_rejected():
    with pytest.raises(ValidationError):
        TestCaseCard.model_validate(_minimal_case(tags=["not_a_real_tag"]))


def test_draft_default_is_false():
    case = TestCaseCard.model_validate(_minimal_case())
    assert case.draft is False


def test_draft_true_for_llm_drafts():
    """LLM-authored cases are marked draft=True until human review (#15.6)."""
    payload = _minimal_case(provenance="llm_authored", draft=True)
    case = TestCaseCard.model_validate(payload)
    assert case.draft is True
    assert case.provenance == Provenance.LLM_AUTHORED


def test_difficulty_now_optional():
    """Per ADR-005, Difficulty is deprecated and Optional. Cases can omit it."""
    payload = _minimal_case()
    payload.pop("difficulty", None)
    case = TestCaseCard.model_validate(payload)
    assert case.difficulty is None


def test_difficulty_still_accepts_legacy_values():
    """Existing 80 fixtures still set difficulty during the deprecation cycle."""
    case = TestCaseCard.model_validate(_minimal_case(difficulty="Long"))
    assert case.difficulty == Difficulty.LONG


def test_test_case_card_full():
    """Full example from DESIGN.md."""
    payload = {
        "id": "CV-OBJ-0042",
        "category": "Object Creation",
        "difficulty": "Medium",
        "task_family": "parameterized_primitive_creation",
        "prompt_variants": [
            "创建一个红色的球体，半径大约 2 米",
            "加一个大概 2 米半径的红球",
            "Add a red sphere, radius about 2 meters",
        ],
        "initial_scene": {"mode": "OBJECT", "objects": []},
        "hard_constraints": {
            "mesh_object_count": {"minimum": 1, "maximum": 1},
            "required_object_types": ["MESH"],
            "bounding_boxes": [
                {
                    "target": "__scene__",
                    "size_range": {"minimum": [3.0, 3.0, 3.0], "maximum": [5.0, 5.0, 5.0]},
                }
            ],
            "materials": [{"target": "*", "base_color": [1.0, 0.0, 0.0, 1.0], "tolerance": 0.2}],
        },
        "topology_policy": {"manifold_required": True, "quad_ratio_min": 0.0, "max_vertex_count": 10000},
        "soft_constraints": [
            {"name": "球体顶点数合理性", "metric": "total_vertices", "direction": "min", "target": 100, "weight": 0.5}
        ],
        "style_intent": {
            "explicit": False,
            "concept": "sphere",
            "concept_aliases": ["ball", "球"],
            "acceptable_styles": ["geometric"],
        },
        "judge_policy": "score",
        "artifact_policy": {"require_screenshot": True, "write_scene_stats": True},
    }
    case = TestCaseCard.model_validate(payload)
    assert case.hard_constraints.bounding_boxes[0].size_range.minimum == [3.0, 3.0, 3.0]
    assert case.topology_policy.max_vertex_count == 10000
    assert len(case.soft_constraints) == 1


# ---------------------------------------------------------------------------
# TestSuite
# ---------------------------------------------------------------------------

def test_test_suite_with_cases():
    suite = TestSuite(
        suite_id="test-suite",
        cases=[TestCaseCard.model_validate(_minimal_case())],
    )
    assert len(suite.cases) == 1


def test_test_suite_from_json(tmp_path):
    case_data = _minimal_case()
    suite_json = {"suite_id": "my-suite", "fixture_version": "3.0", "cases": [case_data]}
    p = tmp_path / "suite.json"
    p.write_text(json.dumps(suite_json))
    suite = TestSuite.from_json(str(p))
    assert suite.suite_id == "my-suite"
    assert len(suite.cases) == 1


def test_test_suite_from_json_list(tmp_path):
    case_data = _minimal_case()
    p = tmp_path / "cases.json"
    p.write_text(json.dumps([case_data]))
    suite = TestSuite.from_json(str(p))
    assert len(suite.cases) == 1


def test_test_suite_from_dir(tmp_path):
    for i in range(3):
        case = _minimal_case(id=f"CV-OBJ-{i:04d}")
        f = tmp_path / f"file_{i}.json"
        f.write_text(json.dumps({"suite_id": f"s{i}", "cases": [case]}))
    suite = TestSuite.from_json_or_dir(str(tmp_path))
    assert len(suite.cases) == 3


# ---------------------------------------------------------------------------
# SceneSnapshot
# ---------------------------------------------------------------------------

def test_scene_snapshot_defaults():
    snap = SceneSnapshot()
    assert snap.total_mesh_objects == 0
    assert snap.bbox_size == [0.0, 0.0, 0.0]


def test_scene_snapshot_bbox_size():
    snap = SceneSnapshot(bbox_min=[-1.0, -1.0, -1.0], bbox_max=[1.0, 1.0, 1.0])
    assert snap.bbox_size == [2.0, 2.0, 2.0]


# ---------------------------------------------------------------------------
# JudgeResult
# ---------------------------------------------------------------------------

def test_judge_result_valid():
    jr = JudgeResult(
        detected_style="cartoon",
        detected_concept="apple",
        style_alignment_pass=True,
        concept_alignment_pass=True,
        semantic=4.0,
        aesthetic=3.5,
        professional=3.0,
        stddev=0.2,
        judged_under_standard="cartoon",
        reasoning="Looks like a cartoon apple.",
        confidence=0.85,
    )
    assert jr.semantic == 4.0


def test_judge_result_score_out_of_range():
    with pytest.raises(ValidationError):
        JudgeResult(
            detected_style="cartoon",
            detected_concept="apple",
            style_alignment_pass=True,
            concept_alignment_pass=True,
            semantic=6.0,  # > 5
            aesthetic=3.0,
            professional=3.0,
            stddev=0.0,
            judged_under_standard="cartoon",
            reasoning="",
            confidence=0.5,
        )


# ---------------------------------------------------------------------------
# Legacy v2.0 schema loads (must not break)
# ---------------------------------------------------------------------------

def test_legacy_v2_loads():
    from nalana_eval.legacy_schema import TestSuite as LegacyTestSuite

    suite = LegacyTestSuite.from_json("fixtures/legacy_v2/sample_cases_v2.json")
    assert len(suite.cases) > 0
    assert suite.fixture_version == "2.0"


def test_legacy_v2_case_fields():
    from nalana_eval.legacy_schema import TestSuite as LegacyTestSuite

    suite = LegacyTestSuite.from_json("fixtures/legacy_v2/sample_cases_v2.json")
    case = suite.cases[0]
    assert hasattr(case, "voice_commands")
    assert len(case.voice_commands) > 0
