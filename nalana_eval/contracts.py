"""JSON 规范化 + safety allowlist.

Forked from Nalana-eval/contracts.py (v2.0) with additions:
- Module-level ALLOWED_* constants (for documentation + test reference)
- compute_normalization_signature(steps) -> str  (judge cache key)
- DELETE_ALL / SELECT_ALL step kinds added for scene_hygiene_safety
"""
from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Optional, Tuple

from nalana_eval.schema import (
    LegacyOperation,
    NormalizedStep,
    OutputContract,
    StepKind,
    TypedCommandPayload,
)


# ---------------------------------------------------------------------------
# Module-level allowlists (constants, not magic strings scattered in code)
# ---------------------------------------------------------------------------

ALLOWED_PRIMITIVES: frozenset[str] = frozenset(
    {
        "CUBE",
        "UV_SPHERE",
        "ICO_SPHERE",
        "CYLINDER",
        "CONE",
        "TORUS",
    }
)

ALLOWED_MODES: frozenset[str] = frozenset({"OBJECT", "EDIT"})
ALLOWED_ROTATE_AXES: frozenset[str] = frozenset({"X", "Y", "Z"})

# Operations that must never reach Blender regardless of context.
# Any step whose bpy.ops name appears here is rejected during normalize_model_output.
_BLOCKED_OPS: frozenset[str] = frozenset(
    {
        "wm.quit_blender",
        "wm.save_mainfile",
        "wm.open_mainfile",
        "wm.link",
        "wm.append",
        "preferences.addon_enable",
        "preferences.addon_disable",
        "script.execute_preset",
        "script.python_file_run",
        "export_scene.obj",
        "export_scene.fbx",
        "export_mesh.stl",
        "import_scene.obj",
        "import_scene.fbx",
    }
)


# ---------------------------------------------------------------------------
# Internal validators
# ---------------------------------------------------------------------------


def _number(value: Any, *, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"Expected a numeric value, got {value!r}")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValueError(f"Value {number} is below minimum {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"Value {number} exceeds maximum {maximum}")
    return number


def _integer(value: Any, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    if not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        else:
            raise ValueError(f"Expected an integer value, got {value!r}")
    number = int(value)
    if minimum is not None and number < minimum:
        raise ValueError(f"Value {number} is below minimum {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"Value {number} exceeds maximum {maximum}")
    return number


def _vector(value: Any, *, length: int = 3) -> List[float]:
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"Expected a {length}-element vector, got {value!r}")
    return [_number(item) for item in value]


def _color(value: Any) -> List[float]:
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list) or len(value) not in {3, 4}:
        raise ValueError("base_color must be a 3- or 4-element list")
    return [_number(item, minimum=0.0, maximum=1.0) for item in value]


def _reject_unknown_args(args: Dict[str, Any], allowed: Iterable[str], *, kind: StepKind) -> None:
    allowed_keys = set(allowed)
    unknown = sorted(set(args) - allowed_keys)
    if unknown:
        raise ValueError(f"{kind.value} does not allow arguments {unknown}")


# ---------------------------------------------------------------------------
# Public API: canonicalize_step
# ---------------------------------------------------------------------------


def canonicalize_step(kind: "StepKind | str", args: Dict[str, Any]) -> NormalizedStep:
    step_kind = StepKind(kind)
    payload = dict(args or {})

    if step_kind == StepKind.ADD_MESH:
        _reject_unknown_args(
            payload,
            {
                "primitive",
                "size",
                "radius",
                "radius1",
                "radius2",
                "depth",
                "vertices",
                "segments",
                "ring_count",
                "subdivisions",
                "major_radius",
                "minor_radius",
                "major_segments",
                "minor_segments",
                "location",
                "rotation",
                "scale",
            },
            kind=step_kind,
        )
        primitive = str(payload.get("primitive", "CUBE")).upper()
        if primitive not in ALLOWED_PRIMITIVES:
            raise ValueError(f"Unsupported primitive {primitive!r}")

        normalized: Dict[str, Any] = {"primitive": primitive}

        if primitive == "CUBE" and "size" in payload:
            normalized["size"] = _number(payload["size"], minimum=0.001)
        if primitive == "UV_SPHERE":
            if "segments" in payload:
                normalized["segments"] = _integer(payload["segments"], minimum=3, maximum=256)
            if "ring_count" in payload:
                normalized["ring_count"] = _integer(payload["ring_count"], minimum=3, maximum=256)
            if "radius" in payload:
                normalized["radius"] = _number(payload["radius"], minimum=0.001)
        if primitive == "ICO_SPHERE":
            if "subdivisions" in payload:
                normalized["subdivisions"] = _integer(payload["subdivisions"], minimum=1, maximum=8)
            if "radius" in payload:
                normalized["radius"] = _number(payload["radius"], minimum=0.001)
        if primitive == "CYLINDER":
            if "vertices" in payload:
                normalized["vertices"] = _integer(payload["vertices"], minimum=3, maximum=256)
            if "radius" in payload:
                normalized["radius"] = _number(payload["radius"], minimum=0.001)
            if "depth" in payload:
                normalized["depth"] = _number(payload["depth"], minimum=0.001)
        if primitive == "CONE":
            if "vertices" in payload:
                normalized["vertices"] = _integer(payload["vertices"], minimum=3, maximum=256)
            if "radius1" in payload:
                normalized["radius1"] = _number(payload["radius1"], minimum=0.0)
            if "radius2" in payload:
                normalized["radius2"] = _number(payload["radius2"], minimum=0.0)
            if "depth" in payload:
                normalized["depth"] = _number(payload["depth"], minimum=0.001)
        if primitive == "TORUS":
            if "major_radius" in payload:
                normalized["major_radius"] = _number(payload["major_radius"], minimum=0.001)
            if "minor_radius" in payload:
                normalized["minor_radius"] = _number(payload["minor_radius"], minimum=0.001)
            if "major_segments" in payload:
                normalized["major_segments"] = _integer(payload["major_segments"], minimum=3, maximum=128)
            if "minor_segments" in payload:
                normalized["minor_segments"] = _integer(payload["minor_segments"], minimum=3, maximum=128)

        for vector_key in {"location", "rotation", "scale"}:
            if vector_key in payload:
                normalized[vector_key] = _vector(payload[vector_key])

        return NormalizedStep(kind=step_kind, args=normalized)

    if step_kind == StepKind.SET_MODE:
        _reject_unknown_args(payload, {"mode"}, kind=step_kind)
        mode = str(payload.get("mode", "OBJECT")).upper()
        if mode.startswith("EDIT"):
            mode = "EDIT"
        if mode not in ALLOWED_MODES:
            raise ValueError(f"Unsupported mode {mode!r}")
        return NormalizedStep(kind=step_kind, args={"mode": mode})

    if step_kind == StepKind.TRANSLATE:
        _reject_unknown_args(payload, {"value"}, kind=step_kind)
        return NormalizedStep(kind=step_kind, args={"value": _vector(payload.get("value", [0.0, 0.0, 0.0]))})

    if step_kind == StepKind.SCALE:
        _reject_unknown_args(payload, {"value"}, kind=step_kind)
        return NormalizedStep(kind=step_kind, args={"value": _vector(payload.get("value", [1.0, 1.0, 1.0]))})

    if step_kind == StepKind.ROTATE:
        _reject_unknown_args(payload, {"value", "orient_axis"}, kind=step_kind)
        axis = str(payload.get("orient_axis", "Z")).upper()
        if axis not in ALLOWED_ROTATE_AXES:
            raise ValueError(f"Unsupported rotate axis {axis!r}")
        return NormalizedStep(
            kind=step_kind,
            args={
                "value": _number(payload.get("value", 0.0)),
                "orient_axis": axis,
            },
        )

    if step_kind == StepKind.BEVEL:
        _reject_unknown_args(payload, {"offset", "segments", "profile"}, kind=step_kind)
        return NormalizedStep(
            kind=step_kind,
            args={
                "offset": _number(payload.get("offset", 0.0), minimum=0.0),
                "segments": _integer(payload.get("segments", 1), minimum=1, maximum=32),
                "profile": _number(payload.get("profile", 0.5), minimum=0.0, maximum=1.0),
            },
        )

    if step_kind == StepKind.INSET:
        _reject_unknown_args(payload, {"thickness", "depth"}, kind=step_kind)
        inset_args: Dict[str, Any] = {
            "thickness": _number(payload.get("thickness", 0.0), minimum=0.0),
        }
        if "depth" in payload:
            inset_args["depth"] = _number(payload["depth"])
        return NormalizedStep(kind=step_kind, args=inset_args)

    if step_kind == StepKind.EXTRUDE_REGION:
        _reject_unknown_args(payload, {"translate"}, kind=step_kind)
        extrude_args: Dict[str, Any] = {}
        if "translate" in payload:
            extrude_args["translate"] = _vector(payload["translate"])
        return NormalizedStep(kind=step_kind, args=extrude_args)

    if step_kind == StepKind.SET_CAMERA:
        _reject_unknown_args(payload, {"name"}, kind=step_kind)
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("SET_CAMERA requires a camera name")
        return NormalizedStep(kind=step_kind, args={"name": name})

    if step_kind == StepKind.SET_MATERIAL:
        _reject_unknown_args(payload, {"name", "base_color"}, kind=step_kind)
        mat_args: Dict[str, Any] = {}
        if "name" in payload:
            name = str(payload["name"]).strip()
            if not name:
                raise ValueError("SET_MATERIAL.name must be non-empty when provided")
            mat_args["name"] = name
        if "base_color" in payload:
            mat_args["base_color"] = _color(payload["base_color"])
        if not mat_args:
            raise ValueError("SET_MATERIAL requires at least one material attribute")
        return NormalizedStep(kind=step_kind, args=mat_args)

    if step_kind == StepKind.DELETE_ALL:
        _reject_unknown_args(payload, set(), kind=step_kind)
        return NormalizedStep(kind=step_kind, args={})

    if step_kind == StepKind.SELECT_ALL:
        _reject_unknown_args(payload, {"action"}, kind=step_kind)
        action = str(payload.get("action", "SELECT")).upper()
        if action not in {"SELECT", "DESELECT", "TOGGLE", "INVERT"}:
            raise ValueError(f"Unsupported SELECT_ALL action {action!r}")
        return NormalizedStep(kind=step_kind, args={"action": action})

    raise ValueError(f"Unsupported benchmark step kind {step_kind!r}")


# ---------------------------------------------------------------------------
# Legacy operation normalizer
# ---------------------------------------------------------------------------


def normalize_legacy_operation(payload: Dict[str, Any]) -> NormalizedStep:
    op = payload.get("op")
    if not isinstance(op, str) or not op:
        raise ValueError("Legacy operations must include an 'op' string")

    raw_params = payload.get("params", payload.get("kwargs", {})) or {}
    if not isinstance(raw_params, dict):
        raise ValueError("Legacy operation params must be a dictionary")

    op_name = op.removeprefix("bpy.ops.")

    if op_name in _BLOCKED_OPS:
        raise ValueError(f"Blocked operation {op!r} is not allowed in benchmark sandbox")

    if op_name == "mesh.primitive_cube_add":
        return canonicalize_step(StepKind.ADD_MESH, {"primitive": "CUBE", **raw_params})
    if op_name == "mesh.primitive_uv_sphere_add":
        return canonicalize_step(StepKind.ADD_MESH, {"primitive": "UV_SPHERE", **raw_params})
    if op_name == "mesh.primitive_ico_sphere_add":
        return canonicalize_step(StepKind.ADD_MESH, {"primitive": "ICO_SPHERE", **raw_params})
    if op_name == "mesh.primitive_cylinder_add":
        return canonicalize_step(StepKind.ADD_MESH, {"primitive": "CYLINDER", **raw_params})
    if op_name == "mesh.primitive_cone_add":
        return canonicalize_step(StepKind.ADD_MESH, {"primitive": "CONE", **raw_params})
    if op_name == "mesh.primitive_torus_add":
        return canonicalize_step(StepKind.ADD_MESH, {"primitive": "TORUS", **raw_params})
    if op_name == "object.mode_set":
        return canonicalize_step(StepKind.SET_MODE, raw_params)
    if op_name == "transform.translate":
        return canonicalize_step(StepKind.TRANSLATE, {"value": raw_params.get("value", [0.0, 0.0, 0.0])})
    if op_name == "transform.resize":
        return canonicalize_step(StepKind.SCALE, {"value": raw_params.get("value", [1.0, 1.0, 1.0])})
    if op_name == "transform.rotate":
        return canonicalize_step(
            StepKind.ROTATE,
            {
                "value": raw_params.get("value", 0.0),
                "orient_axis": raw_params.get("orient_axis", "Z"),
            },
        )
    if op_name == "mesh.bevel":
        return canonicalize_step(StepKind.BEVEL, raw_params)
    if op_name == "mesh.inset":
        return canonicalize_step(StepKind.INSET, raw_params)
    if op_name == "mesh.extrude_region_move":
        translate = None
        if isinstance(raw_params.get("TRANSFORM_OT_translate"), dict):
            translate = raw_params["TRANSFORM_OT_translate"].get("value")
        elif "value" in raw_params:
            translate = raw_params["value"]
        args: Dict[str, Any] = {}
        if translate is not None:
            args["translate"] = translate
        return canonicalize_step(StepKind.EXTRUDE_REGION, args)
    if op_name in {"object.select_all", "object.select_all_by_type"}:
        return canonicalize_step(StepKind.SELECT_ALL, {"action": raw_params.get("action", "SELECT")})
    if op_name == "object.delete":
        return canonicalize_step(StepKind.DELETE_ALL, {})

    raise ValueError(f"Unsupported legacy operation {op!r} in benchmark sandbox")


# ---------------------------------------------------------------------------
# Typed command normalizer
# ---------------------------------------------------------------------------


def normalize_typed_command(payload: Dict[str, Any]) -> List[NormalizedStep]:
    command_type = str(payload.get("type", "")).upper()
    args = payload.get("args", {}) or {}
    if not isinstance(args, dict):
        raise ValueError("Typed command args must be a dictionary")

    if command_type == "ADD_MESH":
        return [canonicalize_step(StepKind.ADD_MESH, args)]
    if command_type == "SET_MODE":
        return [canonicalize_step(StepKind.SET_MODE, args)]
    if command_type == "TRANSFORM":
        steps: List[NormalizedStep] = []
        if "translate" in args:
            steps.append(canonicalize_step(StepKind.TRANSLATE, {"value": args["translate"]}))
        if "scale" in args:
            steps.append(canonicalize_step(StepKind.SCALE, {"value": args["scale"]}))
        if "rotate_euler" in args:
            rotate = args["rotate_euler"]
            if not isinstance(rotate, (list, tuple)) or len(rotate) != 3:
                raise ValueError("TRANSFORM.rotate_euler must be a 3-element vector")
            for axis, value in zip(("X", "Y", "Z"), rotate):
                if float(value) != 0.0:
                    steps.append(canonicalize_step(StepKind.ROTATE, {"value": value, "orient_axis": axis}))
        if not steps:
            raise ValueError("TRANSFORM must include at least one of translate, scale, or rotate_euler")
        return steps
    if command_type == "EDIT_MESH":
        operation = str(args.get("operation", "")).upper()
        op_args = {key: value for key, value in args.items() if key != "operation"}
        if operation == "BEVEL":
            return [canonicalize_step(StepKind.BEVEL, op_args)]
        if operation == "INSET":
            return [canonicalize_step(StepKind.INSET, op_args)]
        if operation == "EXTRUDE_REGION":
            return [canonicalize_step(StepKind.EXTRUDE_REGION, op_args)]
        raise ValueError(f"Unsupported EDIT_MESH operation {operation!r}")
    if command_type == "SET_CAMERA":
        return [canonicalize_step(StepKind.SET_CAMERA, args)]
    if command_type == "SET_MATERIAL":
        return [canonicalize_step(StepKind.SET_MATERIAL, args)]
    if command_type == "DELETE_ALL":
        return [canonicalize_step(StepKind.DELETE_ALL, {})]
    if command_type == "SELECT_ALL":
        return [canonicalize_step(StepKind.SELECT_ALL, args)]

    raise ValueError(f"Unsupported typed benchmark command {command_type!r}")


# ---------------------------------------------------------------------------
# Top-level entry point: normalize_model_output
# ---------------------------------------------------------------------------


def _parse_json_payload(raw_output: Any) -> Any:
    if isinstance(raw_output, str):
        try:
            return json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Model output is not valid JSON: {exc}") from exc
    return raw_output


def normalize_model_output(raw_output: Any) -> Tuple[List[NormalizedStep], OutputContract]:
    """Parse and canonicalize LLM raw output into NormalizedStep list.

    Accepts three contract formats:
    - NORMALIZED:      [{"kind": "ADD_MESH", "args": {...}}, ...]
    - LEGACY_OPS:      [{"op": "bpy.ops.mesh.primitive_cube_add", "params": {...}}, ...]
    - TYPED_COMMANDS:  [{"type": "ADD_MESH", "args": {...}}, ...]

    Also unwraps {"commands": [...]} wrapper if present.
    """
    parsed = _parse_json_payload(raw_output)

    # Unwrap any single-key dict wrapping a list (handles "commands", "steps", "operations", etc.)
    if isinstance(parsed, dict):
        list_vals = [(k, v) for k, v in parsed.items() if isinstance(v, list)]
        if len(list_vals) == 1:
            parsed = list_vals[0][1]

    if isinstance(parsed, dict):
        parsed = [parsed]

    if not isinstance(parsed, list):
        raise ValueError("Model output must be a JSON object or list")

    if not parsed:
        return [], OutputContract.AUTO

    if all(isinstance(item, dict) and "kind" in item for item in parsed):
        return (
            [canonicalize_step(item["kind"], item.get("args", {})) for item in parsed],
            OutputContract.NORMALIZED,
        )

    if all(isinstance(item, dict) and "op" in item for item in parsed):
        return (
            [normalize_legacy_operation(item) for item in parsed],
            OutputContract.LEGACY_OPS,
        )

    if all(isinstance(item, dict) and "type" in item for item in parsed):
        steps: List[NormalizedStep] = []
        for item in parsed:
            steps.extend(normalize_typed_command(item))
        return steps, OutputContract.TYPED_COMMANDS

    raise ValueError("Model output must be consistently normalized, legacy, or typed commands")


# ---------------------------------------------------------------------------
# Signature helper (used by judge cache keying)
# ---------------------------------------------------------------------------


def compute_normalization_signature(steps: List[NormalizedStep]) -> str:
    """Return a stable sha256 hex digest of the step list (for judge cache keys)."""
    payload = [{"kind": s.kind.value, "args": s.args} for s in steps]
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Compile helpers (for backward-compat with legacy_schema._hydrate_compatibility)
# ---------------------------------------------------------------------------


def compile_step_to_legacy_op(step: NormalizedStep) -> LegacyOperation:
    args = dict(step.args)

    if step.kind == StepKind.ADD_MESH:
        primitive = args.pop("primitive")
        op_map = {
            "CUBE": "bpy.ops.mesh.primitive_cube_add",
            "UV_SPHERE": "bpy.ops.mesh.primitive_uv_sphere_add",
            "ICO_SPHERE": "bpy.ops.mesh.primitive_ico_sphere_add",
            "CYLINDER": "bpy.ops.mesh.primitive_cylinder_add",
            "CONE": "bpy.ops.mesh.primitive_cone_add",
            "TORUS": "bpy.ops.mesh.primitive_torus_add",
        }
        return LegacyOperation(op=op_map[primitive], params=args)
    if step.kind == StepKind.SET_MODE:
        return LegacyOperation(op="bpy.ops.object.mode_set", params=dict(args))
    if step.kind == StepKind.TRANSLATE:
        return LegacyOperation(op="bpy.ops.transform.translate", params={"value": args["value"]})
    if step.kind == StepKind.SCALE:
        return LegacyOperation(op="bpy.ops.transform.resize", params={"value": args["value"]})
    if step.kind == StepKind.ROTATE:
        return LegacyOperation(
            op="bpy.ops.transform.rotate",
            params={"value": args["value"], "orient_axis": args.get("orient_axis", "Z")},
        )
    if step.kind == StepKind.BEVEL:
        return LegacyOperation(op="bpy.ops.mesh.bevel", params=dict(args))
    if step.kind == StepKind.INSET:
        return LegacyOperation(op="bpy.ops.mesh.inset", params=dict(args))
    if step.kind == StepKind.EXTRUDE_REGION:
        params: Dict[str, Any] = {}
        if "translate" in args:
            params["TRANSFORM_OT_translate"] = {"value": args["translate"]}
        return LegacyOperation(op="bpy.ops.mesh.extrude_region_move", params=params)
    if step.kind == StepKind.DELETE_ALL:
        return LegacyOperation(op="bpy.ops.object.delete", params={})
    if step.kind == StepKind.SELECT_ALL:
        return LegacyOperation(op="bpy.ops.object.select_all", params=dict(args))

    raise ValueError(f"{step.kind.value} does not have a supported legacy-op compiler")


def compile_step_to_typed_command(step: NormalizedStep) -> Optional[TypedCommandPayload]:
    args = dict(step.args)

    if step.kind == StepKind.ADD_MESH:
        return TypedCommandPayload(type="ADD_MESH", args=args)
    if step.kind == StepKind.SET_MODE:
        return TypedCommandPayload(type="SET_MODE", args=args)
    if step.kind == StepKind.TRANSLATE:
        return TypedCommandPayload(type="TRANSFORM", args={"translate": args["value"]})
    if step.kind == StepKind.SCALE:
        return TypedCommandPayload(type="TRANSFORM", args={"scale": args["value"]})
    if step.kind == StepKind.ROTATE:
        rotate = [0.0, 0.0, 0.0]
        axis = args.get("orient_axis", "Z")
        rotate["XYZ".index(axis)] = args["value"]
        return TypedCommandPayload(type="TRANSFORM", args={"rotate_euler": rotate})
    if step.kind == StepKind.BEVEL:
        return TypedCommandPayload(type="EDIT_MESH", args={"operation": "BEVEL", **args})
    if step.kind == StepKind.INSET:
        return TypedCommandPayload(type="EDIT_MESH", args={"operation": "INSET", **args})
    if step.kind == StepKind.EXTRUDE_REGION:
        typed_args: Dict[str, Any] = {"operation": "EXTRUDE_REGION"}
        if "translate" in args:
            typed_args["translate"] = args["translate"]
        return TypedCommandPayload(type="EDIT_MESH", args=typed_args)
    if step.kind == StepKind.SET_CAMERA:
        return TypedCommandPayload(type="SET_CAMERA", args=args)
    if step.kind == StepKind.SET_MATERIAL:
        return TypedCommandPayload(type="SET_MATERIAL", args=args)
    if step.kind == StepKind.DELETE_ALL:
        return TypedCommandPayload(type="DELETE_ALL", args={})
    if step.kind == StepKind.SELECT_ALL:
        return TypedCommandPayload(type="SELECT_ALL", args=args)
    return None
