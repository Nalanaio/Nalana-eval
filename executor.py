import json
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import bmesh
    import bpy  # pyright: ignore[reportMissingImports]
except ImportError:  # pragma: no cover - Blender-only module
    bmesh = None
    bpy = None

try:
    from .contracts import (
        compile_step_to_legacy_op,
        compile_steps_to_legacy_ops,
        compile_steps_to_typed_commands,
    )
    from .schema import (
        FailureClass,
        InitialScene,
        NormalizedStep,
        OutputContract,
        SceneMeshSnapshot,
        SceneSnapshot,
        TestCaseCard,
    )
except ImportError:  # pragma: no cover - Blender script fallback
    from contracts import compile_step_to_legacy_op, compile_steps_to_legacy_ops, compile_steps_to_typed_commands
    from schema import FailureClass, InitialScene, NormalizedStep, OutputContract, SceneMeshSnapshot, SceneSnapshot, TestCaseCard

from addon.command_exec import execute_command as execute_typed_command
from nalana_core.config import load_config


class BenchmarkSafetyError(RuntimeError):
    pass


@dataclass
class SafetyLimits:
    max_commands: int = 32
    max_new_objects: int = 16
    max_total_vertices: int = 250000
    max_step_seconds: float = 3.0


class DualContractExecutor:
    def __init__(self, repo_root: Optional[str] = None, limits: Optional[SafetyLimits] = None):
        if bpy is None or bmesh is None:  # pragma: no cover - Blender-only module
            raise RuntimeError("DualContractExecutor requires Blender's bpy and bmesh modules")

        self.repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
        self.cfg = load_config(str(self.repo_root))
        self.limits = limits or SafetyLimits()
        self.legacy_registry: Dict[str, Callable[[Dict[str, Any]], None]] = {
            "bpy.ops.mesh.primitive_cube_add": lambda params: bpy.ops.mesh.primitive_cube_add(**params),
            "bpy.ops.mesh.primitive_uv_sphere_add": lambda params: bpy.ops.mesh.primitive_uv_sphere_add(**params),
            "bpy.ops.mesh.primitive_ico_sphere_add": lambda params: bpy.ops.mesh.primitive_ico_sphere_add(**params),
            "bpy.ops.mesh.primitive_cylinder_add": lambda params: bpy.ops.mesh.primitive_cylinder_add(**params),
            "bpy.ops.mesh.primitive_cone_add": lambda params: bpy.ops.mesh.primitive_cone_add(**params),
            "bpy.ops.mesh.primitive_torus_add": lambda params: bpy.ops.mesh.primitive_torus_add(**params),
            "bpy.ops.object.mode_set": lambda params: bpy.ops.object.mode_set(**params),
            "bpy.ops.transform.translate": lambda params: bpy.ops.transform.translate(**params),
            "bpy.ops.transform.resize": lambda params: bpy.ops.transform.resize(**params),
            "bpy.ops.transform.rotate": lambda params: bpy.ops.transform.rotate(**params),
            "bpy.ops.mesh.bevel": lambda params: bpy.ops.mesh.bevel(**params),
            "bpy.ops.mesh.inset": lambda params: bpy.ops.mesh.inset(**params),
            "bpy.ops.mesh.extrude_region_move": lambda params: bpy.ops.mesh.extrude_region_move(**params),
        }

    def reset_scene(self, initial_scene: InitialScene) -> None:
        bpy.ops.wm.read_factory_settings(use_empty=True)

        if initial_scene.objects:
            for seed in initial_scene.objects:
                self._seed_object(seed.model_dump())
        elif initial_scene.active_object == "Cube":
            self._dispatch_normalized_step(
                NormalizedStep(kind="ADD_MESH", args={"primitive": "CUBE"})
            )

        if initial_scene.active_object and initial_scene.active_object in bpy.data.objects:
            bpy.context.view_layer.objects.active = bpy.data.objects[initial_scene.active_object]

        if bpy.context.active_object and initial_scene.mode:
            try:
                bpy.ops.object.mode_set(mode=initial_scene.mode)
            except Exception:
                pass

    def build_reference(self, case: TestCaseCard) -> SceneSnapshot:
        snapshots: List[SceneSnapshot] = []
        for _ in range(case.reference_policy.repeat_runs):
            self.reset_scene(case.initial_scene)
            self.execute_normalized_steps(case.expected_steps)
            snapshots.append(self.capture_scene_snapshot())

        signatures = {snapshot.geometry_signature for snapshot in snapshots}
        if len(signatures) != 1:
            raise BenchmarkSafetyError(
                f"Reference generation for {case.id} was not deterministic: {sorted(signatures)}"
            )
        return snapshots[0]

    def execute_attempt_steps(
        self,
        steps: List[NormalizedStep],
        contract: OutputContract,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        coverage_gaps: List[str] = []
        compiled_legacy = []
        compiled_typed = []

        if len(steps) > self.limits.max_commands:
            raise BenchmarkSafetyError(
                f"Attempt exceeds max command count ({len(steps)} > {self.limits.max_commands})"
            )

        if contract == OutputContract.TYPED_COMMANDS:
            compiled_typed, coverage_gaps = compile_steps_to_typed_commands(steps)
            if coverage_gaps:
                return {
                    "success": False,
                    "failure_class": FailureClass.COVERAGE_GAP,
                    "error_message": coverage_gaps[0],
                    "coverage_gaps": coverage_gaps,
                    "compiled_legacy_ops": compiled_legacy,
                    "compiled_typed_commands": compiled_typed,
                    "execution_latency_ms": (time.perf_counter() - started) * 1000.0,
                }
            self._execute_typed_commands(compiled_typed)
        elif contract == OutputContract.LEGACY_OPS:
            compiled_legacy, coverage_gaps = compile_steps_to_legacy_ops(steps)
            if coverage_gaps:
                return {
                    "success": False,
                    "failure_class": FailureClass.COVERAGE_GAP,
                    "error_message": coverage_gaps[0],
                    "coverage_gaps": coverage_gaps,
                    "compiled_legacy_ops": compiled_legacy,
                    "compiled_typed_commands": compiled_typed,
                    "execution_latency_ms": (time.perf_counter() - started) * 1000.0,
                }
            self._execute_legacy_ops(compiled_legacy)
        else:
            compiled_typed, typed_gaps = compile_steps_to_typed_commands(steps)
            if not typed_gaps:
                self._execute_typed_commands(compiled_typed)
            else:
                compiled_legacy, legacy_gaps = compile_steps_to_legacy_ops(steps)
                coverage_gaps.extend(typed_gaps)
                coverage_gaps.extend(legacy_gaps)
                if legacy_gaps:
                    return {
                        "success": False,
                        "failure_class": FailureClass.COVERAGE_GAP,
                        "error_message": legacy_gaps[0],
                        "coverage_gaps": coverage_gaps,
                        "compiled_legacy_ops": compiled_legacy,
                        "compiled_typed_commands": compiled_typed,
                        "execution_latency_ms": (time.perf_counter() - started) * 1000.0,
                    }
                self._execute_legacy_ops(compiled_legacy)

        snapshot = self.capture_scene_snapshot()
        return {
            "success": True,
            "failure_class": FailureClass.NONE,
            "error_message": None,
            "coverage_gaps": coverage_gaps,
            "compiled_legacy_ops": compiled_legacy,
            "compiled_typed_commands": compiled_typed,
            "execution_latency_ms": (time.perf_counter() - started) * 1000.0,
            "snapshot": snapshot,
        }

    def execute_normalized_steps(self, steps: List[NormalizedStep]) -> None:
        if len(steps) > self.limits.max_commands:
            raise BenchmarkSafetyError(
                f"Attempt exceeds max command count ({len(steps)} > {self.limits.max_commands})"
            )

        baseline_objects, baseline_vertices = self._scene_counters()
        for step in steps:
            started = time.perf_counter()
            self._dispatch_normalized_step(step)
            elapsed = time.perf_counter() - started
            if elapsed > self.limits.max_step_seconds:
                raise BenchmarkSafetyError(
                    f"Step {step.kind.value} exceeded step timeout ({elapsed:.2f}s)"
                )
            self._enforce_scene_quotas(baseline_objects, baseline_vertices)

    def capture_scene_snapshot(self) -> SceneSnapshot:
        mesh_objects: List[SceneMeshSnapshot] = []
        active_object = bpy.context.active_object.name if bpy.context.active_object else None
        total_vertices = 0
        total_faces = 0

        for obj in sorted(bpy.data.objects, key=lambda item: item.name):
            if obj.type != "MESH":
                continue
            mesh = obj.data
            world_vertices = [
                [float(coord) for coord in (obj.matrix_world @ vertex.co)]
                for vertex in mesh.vertices
            ]
            world_faces = [[int(index) for index in polygon.vertices] for polygon in mesh.polygons]
            bm = bmesh.new()
            bm.from_mesh(mesh)
            bm.faces.ensure_lookup_table()
            face_sizes: Dict[str, int] = {}
            for face in bm.faces:
                key = str(len(face.verts))
                face_sizes[key] = face_sizes.get(key, 0) + 1
            manifold = all(edge.is_manifold for edge in bm.edges)
            bm.free()

            mesh_snapshot = SceneMeshSnapshot(
                name=obj.name,
                object_type=obj.type,
                vertex_count=len(mesh.vertices),
                edge_count=len(mesh.edges),
                face_count=len(mesh.polygons),
                face_sizes=face_sizes,
                manifold=manifold,
                world_vertices=world_vertices,
                world_faces=world_faces,
                location=[float(value) for value in obj.location],
                rotation=[float(value) for value in obj.rotation_euler],
                scale=[float(value) for value in obj.scale],
            )
            mesh_objects.append(mesh_snapshot)
            total_vertices += mesh_snapshot.vertex_count
            total_faces += mesh_snapshot.face_count

        signature_payload = {
            "active_object": active_object,
            "meshes": [
                {
                    "name": mesh.name,
                    "vertex_count": mesh.vertex_count,
                    "face_count": mesh.face_count,
                    "face_sizes": mesh.face_sizes,
                    "manifold": mesh.manifold,
                    "vertices": [[round(coord, 6) for coord in vertex] for vertex in mesh.world_vertices],
                    "faces": mesh.world_faces,
                }
                for mesh in mesh_objects
            ],
        }
        signature = sha256(
            json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        return SceneSnapshot(
            active_object=active_object,
            total_objects=len(bpy.data.objects),
            total_mesh_objects=len(mesh_objects),
            total_vertices=total_vertices,
            total_faces=total_faces,
            geometry_signature=signature,
            mesh_objects=mesh_objects,
        )

    def _seed_object(self, seed: Dict[str, Any]) -> None:
        primitive = seed.get("primitive", "CUBE")
        step_args = {
            "primitive": primitive,
            "location": seed.get("location", [0.0, 0.0, 0.0]),
            "rotation": seed.get("rotation", [0.0, 0.0, 0.0]),
            "scale": seed.get("scale", [1.0, 1.0, 1.0]),
        }
        self._dispatch_normalized_step(NormalizedStep(kind="ADD_MESH", args=step_args))
        if seed.get("name") and bpy.context.active_object:
            bpy.context.active_object.name = seed["name"]

    def _dispatch_normalized_step(self, step: NormalizedStep) -> None:
        args = dict(step.args)

        if step.kind.value == "ADD_MESH":
            primitive = args.pop("primitive")
            if primitive == "CUBE":
                bpy.ops.mesh.primitive_cube_add(**args)
            elif primitive == "UV_SPHERE":
                bpy.ops.mesh.primitive_uv_sphere_add(**args)
            elif primitive == "ICO_SPHERE":
                bpy.ops.mesh.primitive_ico_sphere_add(**args)
            elif primitive == "CYLINDER":
                bpy.ops.mesh.primitive_cylinder_add(**args)
            elif primitive == "CONE":
                bpy.ops.mesh.primitive_cone_add(**args)
            elif primitive == "TORUS":
                bpy.ops.mesh.primitive_torus_add(**args)
            else:  # pragma: no cover - normalized steps guard this already
                raise BenchmarkSafetyError(f"Unsupported primitive {primitive}")
            return

        if step.kind.value == "SET_MODE":
            bpy.ops.object.mode_set(mode=args["mode"])
            return

        if step.kind.value == "TRANSLATE":
            bpy.ops.transform.translate(value=args["value"])
            return

        if step.kind.value == "SCALE":
            bpy.ops.transform.resize(value=args["value"])
            return

        if step.kind.value == "ROTATE":
            bpy.ops.transform.rotate(value=args["value"], orient_axis=args["orient_axis"])
            return

        if step.kind.value == "BEVEL":
            bpy.ops.mesh.bevel(**args)
            return

        if step.kind.value == "INSET":
            bpy.ops.mesh.inset(**args)
            return

        if step.kind.value == "EXTRUDE_REGION":
            params = {}
            if "translate" in args:
                params["TRANSFORM_OT_translate"] = {"value": args["translate"]}
            bpy.ops.mesh.extrude_region_move(**params)
            return

        if step.kind.value == "SET_CAMERA":
            camera = bpy.data.objects.get(args["name"])
            if not camera or camera.type != "CAMERA":
                raise BenchmarkSafetyError(f"Camera not found for SET_CAMERA: {args['name']}")
            bpy.context.scene.camera = camera
            return

        if step.kind.value == "SET_MATERIAL":
            active = bpy.context.active_object
            if not active or active.type != "MESH":
                raise BenchmarkSafetyError("SET_MATERIAL requires an active mesh object")
            material_name = args.get("name") or f"{active.name}_Material"
            material = bpy.data.materials.get(material_name)
            if material is None:
                material = bpy.data.materials.new(material_name)
            if "base_color" in args:
                material.use_nodes = False
                rgba = list(args["base_color"])
                if len(rgba) == 3:
                    rgba.append(1.0)
                material.diffuse_color = rgba
            if active.data.materials:
                active.data.materials[0] = material
            else:
                active.data.materials.append(material)
            return

        raise BenchmarkSafetyError(f"Unsupported normalized step {step.kind.value}")

    def _execute_legacy_ops(self, legacy_ops: List[Any]) -> None:
        baseline_objects, baseline_vertices = self._scene_counters()
        for legacy_op in legacy_ops:
            spec = self.legacy_registry.get(legacy_op.op)
            if spec is None:
                raise BenchmarkSafetyError(f"Legacy operation {legacy_op.op} is not allowlisted")
            started = time.perf_counter()
            spec(dict(legacy_op.params))
            elapsed = time.perf_counter() - started
            if elapsed > self.limits.max_step_seconds:
                raise BenchmarkSafetyError(
                    f"Legacy operation {legacy_op.op} exceeded step timeout ({elapsed:.2f}s)"
                )
            self._enforce_scene_quotas(baseline_objects, baseline_vertices)

    def _execute_typed_commands(self, typed_commands: List[Any]) -> None:
        baseline_objects, baseline_vertices = self._scene_counters()
        for command in typed_commands:
            started = time.perf_counter()
            result = execute_typed_command(command.model_dump(), self.cfg)
            elapsed = time.perf_counter() - started
            if elapsed > self.limits.max_step_seconds:
                raise BenchmarkSafetyError(
                    f"Typed command {command.type} exceeded step timeout ({elapsed:.2f}s)"
                )
            if not result.get("ok"):
                raise BenchmarkSafetyError(result.get("error", f"Typed command {command.type} failed"))
            self._enforce_scene_quotas(baseline_objects, baseline_vertices)

    def _scene_counters(self) -> Tuple[int, int]:
        object_count = len(bpy.data.objects)
        vertex_count = 0
        for obj in bpy.data.objects:
            if obj.type == "MESH":
                vertex_count += len(obj.data.vertices)
        return object_count, vertex_count

    def _enforce_scene_quotas(self, baseline_objects: int, baseline_vertices: int) -> None:
        object_count, vertex_count = self._scene_counters()
        if object_count - baseline_objects > self.limits.max_new_objects:
            raise BenchmarkSafetyError(
                f"Attempt exceeded object quota ({object_count - baseline_objects} > {self.limits.max_new_objects})"
            )
        if vertex_count > self.limits.max_total_vertices:
            raise BenchmarkSafetyError(
                f"Attempt exceeded vertex quota ({vertex_count} > {self.limits.max_total_vertices})"
            )
        if vertex_count < baseline_vertices:
            return
