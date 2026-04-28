"""Constraint evaluator — L2 main logic. Runs in main Python process."""
from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple

from nalana_eval.schema import (
    BoundingBoxConstraint,
    EvaluationResult,
    FailureClass,
    HardConstraints,
    MaterialConstraint,
    SceneMeshSnapshot,
    SceneSnapshot,
    SoftConstraint,
    SoftDirection,
    TestCaseCard,
    TopologyPolicy,
)

logger = logging.getLogger(__name__)


class ConstraintEvaluator:
    def evaluate(
        self,
        case: TestCaseCard,
        snapshot: SceneSnapshot,
        execution_success: bool,
    ) -> EvaluationResult:
        if not execution_success:
            return EvaluationResult(
                hard_pass=False,
                topology_pass=False,
                soft_score=0.0,
                failure_class=FailureClass.EXECUTION_ERROR,
                failure_reason="Blender execution failed",
            )

        hard_pass, hard_violations = self._check_hard(case.hard_constraints, snapshot)
        topo_pass, topo_violations = self._check_topology(case.topology_policy, snapshot)
        soft_score = self._score_soft(case.soft_constraints, snapshot)

        if not hard_pass:
            failure_class = FailureClass.CONSTRAINT_FAILED
            failure_reason = "; ".join(hard_violations)
        elif not topo_pass:
            failure_class = FailureClass.TOPOLOGY_FAILED
            failure_reason = "; ".join(topo_violations)
        else:
            failure_class = FailureClass.NONE
            failure_reason = None

        return EvaluationResult(
            hard_pass=hard_pass,
            topology_pass=topo_pass,
            soft_score=soft_score,
            hard_violations=hard_violations,
            topology_violations=topo_violations,
            failure_class=failure_class,
            failure_reason=failure_reason,
        )

    # ------------------------------------------------------------------
    # Hard constraints
    # ------------------------------------------------------------------

    def _check_hard(
        self, hc: HardConstraints, snap: SceneSnapshot
    ) -> Tuple[bool, List[str]]:
        violations: List[str] = []

        if hc.mesh_object_count is not None:
            if not hc.mesh_object_count.matches(snap.total_mesh_objects):
                violations.append(
                    f"mesh_object_count: got {snap.total_mesh_objects}, "
                    f"expected {hc.mesh_object_count}"
                )

        for req_type in hc.required_object_types:
            if not any(m.object_type == req_type for m in snap.mesh_objects):
                violations.append(f"required_object_type {req_type!r} not found")

        for req_name in hc.required_named_objects:
            if not any(m.name == req_name for m in snap.mesh_objects):
                violations.append(f"required named object {req_name!r} not found")

        for bbox_c in hc.bounding_boxes:
            v = self._check_bbox(bbox_c, snap)
            if v:
                violations.append(v)

        for mat_c in hc.materials:
            v = self._check_material(mat_c, snap)
            if v:
                violations.append(v)

        if hc.scene_mutation and hc.scene_mutation.preserve_seed_objects:
            # Seed object names are stored in required_named_objects;
            # violation already captured above.
            pass

        return (len(violations) == 0, violations)

    def _check_bbox(
        self, constraint: BoundingBoxConstraint, snap: SceneSnapshot
    ) -> Optional[str]:
        target = constraint.target
        sr = constraint.size_range

        if target == "__scene__":
            size = snap.bbox_size
            label = "scene bbox"
        elif target == "*":
            # Any single mesh must satisfy; pass if at least one does
            for mesh in snap.mesh_objects:
                size = [
                    mesh.bbox_max[i] - mesh.bbox_min[i] for i in range(3)
                ]
                if self._size_in_range(size, sr):
                    return None
            if not snap.mesh_objects:
                return "bounding_box target='*': no mesh objects in scene"
            size = [
                snap.mesh_objects[0].bbox_max[i] - snap.mesh_objects[0].bbox_min[i]
                for i in range(3)
            ]
            label = "any mesh bbox"
        else:
            mesh = next((m for m in snap.mesh_objects if m.name == target), None)
            if mesh is None:
                return f"bounding_box target={target!r}: object not found"
            size = [mesh.bbox_max[i] - mesh.bbox_min[i] for i in range(3)]
            label = f"{target} bbox"

        if not self._size_in_range(size, sr):
            return (
                f"{label}: size {[round(s, 3) for s in size]} "
                f"not in [{sr.minimum}, {sr.maximum}]"
            )
        return None

    @staticmethod
    def _size_in_range(size: List[float], sr: any) -> bool:  # type: ignore[valid-type]
        if sr.minimum is not None:
            if any(size[i] < sr.minimum[i] for i in range(3)):
                return False
        if sr.maximum is not None:
            if any(size[i] > sr.maximum[i] for i in range(3)):
                return False
        return True

    def _check_material(
        self, constraint: MaterialConstraint, snap: SceneSnapshot
    ) -> Optional[str]:
        if constraint.base_color is None:
            return None

        target = constraint.target
        tol = constraint.tolerance

        if target == "*":
            candidates = snap.mesh_objects
        else:
            candidates = [m for m in snap.mesh_objects if m.name == target]
            if not candidates:
                return f"material target={target!r}: object not found"

        for mesh in candidates:
            for mat in mesh.materials:
                if self._color_distance(mat.base_color, constraint.base_color) <= tol:
                    return None

        got_colors = [
            mat.base_color for mesh in candidates for mat in mesh.materials
        ]
        return (
            f"material color: none of {got_colors} "
            f"within tolerance {tol} of {constraint.base_color}"
        )

    @staticmethod
    def _color_distance(a: List[float], b: List[float]) -> float:
        n = min(len(a), len(b), 4)
        return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(n)))

    # ------------------------------------------------------------------
    # Topology constraints
    # ------------------------------------------------------------------

    def _check_topology(
        self, tp: TopologyPolicy, snap: SceneSnapshot
    ) -> Tuple[bool, List[str]]:
        violations: List[str] = []

        if tp.manifold_required and not snap.manifold:
            non_manifold = [m.name for m in snap.mesh_objects if not m.manifold]
            violations.append(f"manifold required but non-manifold: {non_manifold}")

        if tp.quad_ratio_min > 0.0 and snap.quad_ratio < tp.quad_ratio_min:
            violations.append(
                f"quad_ratio {snap.quad_ratio:.3f} < minimum {tp.quad_ratio_min:.3f}"
            )

        if tp.max_face_count is not None and snap.total_faces > tp.max_face_count:
            violations.append(
                f"total_faces {snap.total_faces} > max {tp.max_face_count}"
            )

        if tp.max_vertex_count is not None and snap.total_vertices > tp.max_vertex_count:
            violations.append(
                f"total_vertices {snap.total_vertices} > max {tp.max_vertex_count}"
            )

        return (len(violations) == 0, violations)

    # ------------------------------------------------------------------
    # Soft constraints
    # ------------------------------------------------------------------

    def _score_soft(
        self, constraints: List[SoftConstraint], snap: SceneSnapshot
    ) -> float:
        if not constraints:
            return 1.0

        total_weight = sum(c.weight for c in constraints)
        weighted_score = 0.0

        for sc in constraints:
            value = self._get_metric(sc.metric.value, snap)
            score = self._score_one(sc, value)
            weighted_score += score * sc.weight

        return min(1.0, max(0.0, weighted_score / total_weight))

    @staticmethod
    def _get_metric(metric: str, snap: SceneSnapshot) -> float:
        if metric == "total_objects":
            return float(snap.total_objects)
        if metric == "total_mesh_objects":
            return float(snap.total_mesh_objects)
        if metric == "total_vertices":
            return float(snap.total_vertices)
        if metric == "total_faces":
            return float(snap.total_faces)
        if metric == "quad_ratio":
            return snap.quad_ratio
        if metric == "new_object_count":
            return float(snap.total_mesh_objects)
        return 0.0

    @staticmethod
    def _score_one(sc: SoftConstraint, value: float) -> float:
        target = sc.target
        tol = sc.tolerance if sc.tolerance > 0 else max(abs(target) * 0.1, 1.0)

        if sc.direction == SoftDirection.EXACT:
            delta = abs(value - target)
            return max(0.0, 1.0 - delta / tol)
        if sc.direction == SoftDirection.MIN:
            if value >= target:
                return 1.0
            delta = target - value
            return max(0.0, 1.0 - delta / tol)
        if sc.direction == SoftDirection.MAX:
            if value <= target:
                return 1.0
            delta = value - target
            return max(0.0, 1.0 - delta / tol)
        return 0.0
