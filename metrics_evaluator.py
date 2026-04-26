from typing import Dict, List, Sequence, Tuple

import numpy as np

try:
    from .schema import NormalizedStep, SceneSnapshot, TopologyScore
except ImportError:  # pragma: no cover - Blender script fallback
    from schema import NormalizedStep, SceneSnapshot, TopologyScore


class MetricsEvaluator:

    @staticmethod
    def calculate_topology_score(snapshot: SceneSnapshot) -> TopologyScore:
        meshes = snapshot.mesh_objects
        if not meshes:
            return TopologyScore()

        total_faces = sum(m.face_count for m in meshes)

        if total_faces > 0:
            quad_ratio = sum(m.face_sizes.get("4", 0) for m in meshes) / total_faces
            face_quality_score = sum(m.face_quality_score * m.face_count for m in meshes) / total_faces
        else:
            quad_ratio = 0.0
            face_quality_score = 1.0

        return TopologyScore(
            manifold=all(m.manifold for m in meshes),
            loose_geometry_count=sum(m.loose_geometry_count for m in meshes),
            quad_ratio=quad_ratio,
            face_quality_score=face_quality_score,
            flipped_face_count=sum(m.flipped_face_count for m in meshes),
            overlapping_verts=sum(m.overlapping_verts for m in meshes),
            duplicate_faces=sum(m.duplicate_faces for m in meshes),
        )

    @staticmethod
    def calculate_command_accuracy(expected: List[NormalizedStep], actual: List[NormalizedStep]) -> float:
        max_len = max(len(expected), len(actual))
        if max_len == 0:
            return 1.0
        matches = 0
        for exp_step, act_step in zip(expected, actual):
            if exp_step.kind == act_step.kind:
                matches += 1
        return matches / max_len

    @staticmethod
    def calculate_parameter_accuracy(expected: List[NormalizedStep], actual: List[NormalizedStep]) -> float:
        max_len = max(len(expected), len(actual))
        if max_len == 0:
            return 1.0

        score = 0.0
        for exp_step, act_step in zip(expected, actual):
            if exp_step.kind != act_step.kind:
                continue
            score += MetricsEvaluator._score_param_dict(exp_step.args, act_step.args)
        return score / max_len

    @staticmethod
    def calculate_sequence_accuracy(expected: List[NormalizedStep], actual: List[NormalizedStep]) -> float:
        expected_kinds = [step.kind.value for step in expected]
        actual_kinds = [step.kind.value for step in actual]
        max_len = max(len(expected_kinds), len(actual_kinds))
        if max_len == 0:
            return 1.0
        lcs = MetricsEvaluator._lcs_length(expected_kinds, actual_kinds)
        return lcs / max_len

    @staticmethod
    def calculate_chamfer_distance(
        reference: SceneSnapshot,
        candidate: SceneSnapshot,
        *,
        max_points: int = 256,
    ) -> Tuple[float, str]:
        reference_points, ref_mode = MetricsEvaluator._sample_scene_points(reference, max_points=max_points)
        candidate_points, cand_mode = MetricsEvaluator._sample_scene_points(candidate, max_points=max_points)
        sampling_mode = ref_mode if ref_mode == cand_mode else f"{ref_mode}->{cand_mode}"

        if reference_points.size == 0 or candidate_points.size == 0:
            return float("inf"), sampling_mode

        ref_to_cand = MetricsEvaluator._min_pairwise_distance(reference_points, candidate_points)
        cand_to_ref = MetricsEvaluator._min_pairwise_distance(candidate_points, reference_points)
        chamfer = float(ref_to_cand.mean() + cand_to_ref.mean()) / 2.0
        return chamfer, sampling_mode

    @staticmethod
    def calculate_pass_at_k(results: Sequence[bool], k: int = 3) -> float:
        if k <= 0:
            return 0.0
        truncated = list(results[:k])
        if not truncated:
            return 0.0
        return 1.0 if any(truncated) else 0.0

    @staticmethod
    def _sample_scene_points(snapshot: SceneSnapshot, *, max_points: int) -> Tuple[np.ndarray, str]:
        triangles: List[np.ndarray] = []
        areas: List[float] = []
        vertices: List[np.ndarray] = []

        for mesh in snapshot.mesh_objects:
            mesh_vertices = np.asarray(mesh.world_vertices, dtype=float)
            if mesh_vertices.size == 0:
                continue
            vertices.append(mesh_vertices)
            for face in mesh.world_faces:
                if len(face) < 3:
                    continue
                anchor = mesh_vertices[face[0]]
                for index in range(1, len(face) - 1):
                    triangle = np.asarray(
                        [
                            anchor,
                            mesh_vertices[face[index]],
                            mesh_vertices[face[index + 1]],
                        ],
                        dtype=float,
                    )
                    area = np.linalg.norm(np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])) / 2.0
                    if area > 0:
                        triangles.append(triangle)
                        areas.append(float(area))

        if triangles and sum(areas) > 0:
            rng = np.random.default_rng(0)
            area_array = np.asarray(areas, dtype=float)
            cdf = np.cumsum(area_array / area_array.sum())
            samples = np.empty((max_points, 3), dtype=float)
            for index in range(max_points):
                r = rng.random()
                tri_index = int(np.searchsorted(cdf, r, side="right"))
                tri_index = min(tri_index, len(triangles) - 1)
                triangle = triangles[tri_index]
                u = rng.random()
                v = rng.random()
                if u + v > 1.0:
                    u = 1.0 - u
                    v = 1.0 - v
                samples[index] = triangle[0] + u * (triangle[1] - triangle[0]) + v * (triangle[2] - triangle[0])
            return samples, "surface"

        if vertices:
            all_vertices = np.concatenate(vertices, axis=0)
            if len(all_vertices) <= max_points:
                return all_vertices, "vertices"
            indices = np.linspace(0, len(all_vertices) - 1, num=max_points, dtype=int)
            return all_vertices[indices], "vertices"

        return np.empty((0, 3), dtype=float), "empty"

    @staticmethod
    def _min_pairwise_distance(points_a: np.ndarray, points_b: np.ndarray) -> np.ndarray:
        diffs = points_a[:, None, :] - points_b[None, :, :]
        squared = np.sum(diffs * diffs, axis=2)
        return np.sqrt(np.min(squared, axis=1))

    @staticmethod
    def _score_param_dict(expected: Dict[str, object], actual: Dict[str, object]) -> float:
        if not expected and not actual:
            return 1.0
        keys = sorted(set(expected) | set(actual))
        if not keys:
            return 1.0
        scores = []
        for key in keys:
            if key not in expected or key not in actual:
                scores.append(0.0)
                continue
            scores.append(MetricsEvaluator._score_param_value(expected[key], actual[key]))
        return sum(scores) / len(scores)

    @staticmethod
    def _score_param_value(expected: object, actual: object) -> float:
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            tolerance = max(1e-4, abs(float(expected)) * 0.05)
            return 1.0 if abs(float(expected) - float(actual)) <= tolerance else 0.0

        if (
            isinstance(expected, list)
            and isinstance(actual, list)
            and len(expected) == len(actual)
            and all(isinstance(item, (int, float)) for item in expected)
            and all(isinstance(item, (int, float)) for item in actual)
        ):
            parts = [
                MetricsEvaluator._score_param_value(exp_item, act_item)
                for exp_item, act_item in zip(expected, actual)
            ]
            return sum(parts) / len(parts) if parts else 1.0

        return 1.0 if expected == actual else 0.0

    @staticmethod
    def _lcs_length(left: Sequence[str], right: Sequence[str]) -> int:
        if not left or not right:
            return 0
        widths = len(right) + 1
        prev = [0] * widths
        for left_value in left:
            curr = [0] * widths
            for index, right_value in enumerate(right, start=1):
                if left_value == right_value:
                    curr[index] = prev[index - 1] + 1
                else:
                    curr[index] = max(prev[index], curr[index - 1])
            prev = curr
        return prev[-1]

