"""Unit tests for ConstraintEvaluator."""
from __future__ import annotations

import pytest

from nalana_eval.evaluator import ConstraintEvaluator
from nalana_eval.schema import (
    ArtifactPolicy,
    BoundingBoxConstraint,
    BoundingBoxSizeRange,
    Category,
    CountRange,
    Difficulty,
    EvaluationResult,
    FailureClass,
    HardConstraints,
    InitialScene,
    JudgePolicy,
    MaterialConstraint,
    MaterialSnapshot,
    SceneMeshSnapshot,
    SceneSnapshot,
    SceneMutationPolicy,
    SoftConstraint,
    SoftDirection,
    SoftMetric,
    StyleIntent,
    TaskFamily,
    TestCaseCard,
    TopologyPolicy,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_case(
    hard: HardConstraints | None = None,
    topo: TopologyPolicy | None = None,
    soft: list[SoftConstraint] | None = None,
) -> TestCaseCard:
    return TestCaseCard(
        id="TEST-001",
        category=Category.OBJECT_CREATION,
        difficulty=Difficulty.SHORT,
        task_family=TaskFamily.PRIMITIVE_CREATION,
        prompt_variants=["Add a cube"],
        initial_scene=InitialScene(),
        hard_constraints=hard or HardConstraints(),
        topology_policy=topo or TopologyPolicy(),
        soft_constraints=soft or [],
        style_intent=StyleIntent(),
        judge_policy=JudgePolicy.SKIP,
        artifact_policy=ArtifactPolicy(),
    )


def _make_cube_snap(
    n_objects: int = 1,
    bbox_min: list[float] | None = None,
    bbox_max: list[float] | None = None,
    base_color: list[float] | None = None,
    manifold: bool = True,
    quad_ratio: float = 1.0,
    total_faces: int = 6,
    total_vertices: int = 8,
) -> SceneSnapshot:
    bmin = bbox_min or [-1.0, -1.0, -1.0]
    bmax = bbox_max or [1.0, 1.0, 1.0]
    mats = []
    if base_color:
        mats = [MaterialSnapshot(name="Mat", base_color=base_color)]
    meshes = [
        SceneMeshSnapshot(
            name=f"Cube{i}",
            object_type="MESH",
            vertex_count=total_vertices,
            face_count=total_faces,
            manifold=manifold,
            bbox_min=bmin,
            bbox_max=bmax,
            materials=mats,
        )
        for i in range(n_objects)
    ]
    return SceneSnapshot(
        total_objects=n_objects,
        total_mesh_objects=n_objects,
        total_vertices=total_vertices * n_objects,
        total_faces=total_faces * n_objects,
        quad_ratio=quad_ratio,
        manifold=manifold,
        bbox_min=bmin,
        bbox_max=bmax,
        mesh_objects=meshes,
    )


E = ConstraintEvaluator()


# ---------------------------------------------------------------------------
# Execution failure fast-path
# ---------------------------------------------------------------------------


def test_execution_failure_returns_immediately():
    case = _make_case()
    snap = _make_cube_snap()
    result = E.evaluate(case, snap, execution_success=False)
    assert result.hard_pass is False
    assert result.failure_class == FailureClass.EXECUTION_ERROR


# ---------------------------------------------------------------------------
# mesh_object_count
# ---------------------------------------------------------------------------


def test_mesh_object_count_minimum_pass():
    case = _make_case(hard=HardConstraints(mesh_object_count=CountRange(minimum=1)))
    result = E.evaluate(case, _make_cube_snap(n_objects=1), True)
    assert result.hard_pass is True


def test_mesh_object_count_minimum_fail():
    case = _make_case(hard=HardConstraints(mesh_object_count=CountRange(minimum=2)))
    result = E.evaluate(case, _make_cube_snap(n_objects=1), True)
    assert result.hard_pass is False
    assert result.failure_class == FailureClass.CONSTRAINT_FAILED


def test_mesh_object_count_maximum_pass():
    case = _make_case(hard=HardConstraints(mesh_object_count=CountRange(maximum=0)))
    snap = SceneSnapshot()  # empty scene
    result = E.evaluate(case, snap, True)
    assert result.hard_pass is True


def test_mesh_object_count_maximum_fail():
    case = _make_case(hard=HardConstraints(mesh_object_count=CountRange(maximum=0)))
    result = E.evaluate(case, _make_cube_snap(n_objects=1), True)
    assert result.hard_pass is False


# ---------------------------------------------------------------------------
# required_object_types
# ---------------------------------------------------------------------------


def test_required_object_type_present():
    case = _make_case(hard=HardConstraints(required_object_types=["MESH"]))
    result = E.evaluate(case, _make_cube_snap(), True)
    assert result.hard_pass is True


def test_required_object_type_absent():
    case = _make_case(hard=HardConstraints(required_object_types=["CURVE"]))
    result = E.evaluate(case, _make_cube_snap(), True)
    assert result.hard_pass is False


# ---------------------------------------------------------------------------
# required_named_objects
# ---------------------------------------------------------------------------


def test_required_named_object_present():
    snap = _make_cube_snap()
    snap.mesh_objects[0].name = "Cube"
    case = _make_case(hard=HardConstraints(required_named_objects=["Cube"]))
    result = E.evaluate(case, snap, True)
    assert result.hard_pass is True


def test_required_named_object_absent():
    case = _make_case(hard=HardConstraints(required_named_objects=["MissingObject"]))
    result = E.evaluate(case, _make_cube_snap(), True)
    assert result.hard_pass is False


# ---------------------------------------------------------------------------
# bounding_box
# ---------------------------------------------------------------------------


def test_bbox_scene_pass():
    case = _make_case(
        hard=HardConstraints(
            bounding_boxes=[
                BoundingBoxConstraint(
                    target="__scene__",
                    size_range=BoundingBoxSizeRange(
                        minimum=[1.5, 1.5, 1.5],
                        maximum=[2.5, 2.5, 2.5],
                    ),
                )
            ]
        )
    )
    snap = _make_cube_snap(bbox_min=[-1, -1, -1], bbox_max=[1, 1, 1])  # size [2,2,2]
    result = E.evaluate(case, snap, True)
    assert result.hard_pass is True


def test_bbox_scene_fail_too_small():
    case = _make_case(
        hard=HardConstraints(
            bounding_boxes=[
                BoundingBoxConstraint(
                    target="__scene__",
                    size_range=BoundingBoxSizeRange(minimum=[3.0, 3.0, 3.0]),
                )
            ]
        )
    )
    snap = _make_cube_snap(bbox_min=[-1, -1, -1], bbox_max=[1, 1, 1])
    result = E.evaluate(case, snap, True)
    assert result.hard_pass is False


def test_bbox_named_object_not_found():
    case = _make_case(
        hard=HardConstraints(
            bounding_boxes=[
                BoundingBoxConstraint(
                    target="Ghost",
                    size_range=BoundingBoxSizeRange(minimum=[1.0, 1.0, 1.0]),
                )
            ]
        )
    )
    result = E.evaluate(case, _make_cube_snap(), True)
    assert result.hard_pass is False


def test_bbox_wildcard_any_satisfies():
    case = _make_case(
        hard=HardConstraints(
            bounding_boxes=[
                BoundingBoxConstraint(
                    target="*",
                    size_range=BoundingBoxSizeRange(
                        minimum=[1.5, 1.5, 1.5],
                        maximum=[2.5, 2.5, 2.5],
                    ),
                )
            ]
        )
    )
    snap = _make_cube_snap(bbox_min=[-1, -1, -1], bbox_max=[1, 1, 1])
    result = E.evaluate(case, snap, True)
    assert result.hard_pass is True


# ---------------------------------------------------------------------------
# material color
# ---------------------------------------------------------------------------


def test_material_color_pass():
    case = _make_case(
        hard=HardConstraints(
            materials=[MaterialConstraint(target="*", base_color=[1.0, 0.0, 0.0, 1.0], tolerance=0.2)]
        )
    )
    snap = _make_cube_snap(base_color=[1.0, 0.05, 0.0, 1.0])
    result = E.evaluate(case, snap, True)
    assert result.hard_pass is True


def test_material_color_fail():
    case = _make_case(
        hard=HardConstraints(
            materials=[MaterialConstraint(target="*", base_color=[1.0, 0.0, 0.0, 1.0], tolerance=0.1)]
        )
    )
    snap = _make_cube_snap(base_color=[0.0, 0.0, 1.0, 1.0])  # blue, not red
    result = E.evaluate(case, snap, True)
    assert result.hard_pass is False


def test_material_no_base_color_skipped():
    # MaterialConstraint with no base_color is always satisfied
    case = _make_case(
        hard=HardConstraints(materials=[MaterialConstraint(target="*")])
    )
    result = E.evaluate(case, _make_cube_snap(), True)
    assert result.hard_pass is True


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------


def test_topology_manifold_required_pass():
    case = _make_case(topo=TopologyPolicy(manifold_required=True))
    snap = _make_cube_snap(manifold=True)
    result = E.evaluate(case, snap, True)
    assert result.topology_pass is True


def test_topology_manifold_required_fail():
    case = _make_case(topo=TopologyPolicy(manifold_required=True))
    snap = _make_cube_snap(manifold=False)
    result = E.evaluate(case, snap, True)
    assert result.topology_pass is False
    assert result.failure_class == FailureClass.TOPOLOGY_FAILED


def test_topology_quad_ratio_pass():
    case = _make_case(topo=TopologyPolicy(quad_ratio_min=0.9))
    snap = _make_cube_snap(quad_ratio=1.0)
    result = E.evaluate(case, snap, True)
    assert result.topology_pass is True


def test_topology_quad_ratio_fail():
    case = _make_case(topo=TopologyPolicy(quad_ratio_min=0.9))
    snap = _make_cube_snap(quad_ratio=0.5)
    result = E.evaluate(case, snap, True)
    assert result.topology_pass is False


def test_topology_max_faces_pass():
    case = _make_case(topo=TopologyPolicy(max_face_count=100))
    snap = _make_cube_snap(total_faces=6)
    result = E.evaluate(case, snap, True)
    assert result.topology_pass is True


def test_topology_max_faces_fail():
    case = _make_case(topo=TopologyPolicy(max_face_count=5))
    snap = _make_cube_snap(total_faces=6)
    result = E.evaluate(case, snap, True)
    assert result.topology_pass is False


def test_topology_max_vertices_fail():
    case = _make_case(topo=TopologyPolicy(max_vertex_count=4))
    snap = _make_cube_snap(total_vertices=8)
    result = E.evaluate(case, snap, True)
    assert result.topology_pass is False


# ---------------------------------------------------------------------------
# Soft constraints
# ---------------------------------------------------------------------------


def test_soft_no_constraints_returns_one():
    case = _make_case(soft=[])
    result = E.evaluate(case, _make_cube_snap(), True)
    assert result.soft_score == 1.0


def test_soft_exact_hit():
    sc = SoftConstraint(
        name="exact vertices",
        metric=SoftMetric.TOTAL_VERTICES,
        direction=SoftDirection.EXACT,
        target=8.0,
        tolerance=2.0,
        weight=1.0,
    )
    case = _make_case(soft=[sc])
    snap = _make_cube_snap(total_vertices=8)
    result = E.evaluate(case, snap, True)
    assert result.soft_score == pytest.approx(1.0)


def test_soft_exact_miss():
    sc = SoftConstraint(
        name="exact vertices",
        metric=SoftMetric.TOTAL_VERTICES,
        direction=SoftDirection.EXACT,
        target=8.0,
        tolerance=2.0,
        weight=1.0,
    )
    case = _make_case(soft=[sc])
    snap = _make_cube_snap(total_vertices=14)  # delta=6, tol=2 → score=0
    result = E.evaluate(case, snap, True)
    assert result.soft_score == pytest.approx(0.0)


def test_soft_min_satisfied():
    sc = SoftConstraint(
        name="min verts",
        metric=SoftMetric.TOTAL_VERTICES,
        direction=SoftDirection.MIN,
        target=5.0,
        tolerance=2.0,
        weight=1.0,
    )
    case = _make_case(soft=[sc])
    snap = _make_cube_snap(total_vertices=8)
    result = E.evaluate(case, snap, True)
    assert result.soft_score == pytest.approx(1.0)


def test_soft_max_satisfied():
    sc = SoftConstraint(
        name="max objects",
        metric=SoftMetric.TOTAL_MESH_OBJECTS,
        direction=SoftDirection.MAX,
        target=5.0,
        tolerance=2.0,
        weight=1.0,
    )
    case = _make_case(soft=[sc])
    snap = _make_cube_snap(n_objects=2)
    result = E.evaluate(case, snap, True)
    assert result.soft_score == pytest.approx(1.0)


def test_soft_weighted_average():
    sc1 = SoftConstraint(
        name="a", metric=SoftMetric.TOTAL_VERTICES, direction=SoftDirection.EXACT,
        target=8.0, tolerance=0.1, weight=1.0,
    )
    sc2 = SoftConstraint(
        name="b", metric=SoftMetric.TOTAL_FACES, direction=SoftDirection.EXACT,
        target=6.0, tolerance=0.1, weight=3.0,
    )
    case = _make_case(soft=[sc1, sc2])
    snap = _make_cube_snap(total_vertices=8, total_faces=6)
    result = E.evaluate(case, snap, True)
    assert result.soft_score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# pass_overall logic
# ---------------------------------------------------------------------------


def test_pass_overall_requires_both_hard_and_topology():
    case = _make_case(
        hard=HardConstraints(mesh_object_count=CountRange(minimum=1)),
        topo=TopologyPolicy(manifold_required=True),
    )
    snap = _make_cube_snap(manifold=False)
    result = E.evaluate(case, snap, True)
    # hard passes, topology fails → overall fail
    assert result.hard_pass is True
    assert result.topology_pass is False
    assert result.failure_class == FailureClass.TOPOLOGY_FAILED


def test_pass_overall_hard_fail_topology_not_checked_for_class():
    case = _make_case(
        hard=HardConstraints(mesh_object_count=CountRange(minimum=3)),
        topo=TopologyPolicy(manifold_required=True),
    )
    snap = _make_cube_snap(n_objects=1, manifold=False)
    result = E.evaluate(case, snap, True)
    assert result.hard_pass is False
    assert result.failure_class == FailureClass.CONSTRAINT_FAILED
