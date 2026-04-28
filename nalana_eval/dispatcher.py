"""JSON → bpy.ops dispatcher. Runs inside Blender; stdlib + bpy ONLY — no pydantic."""
# ruff: noqa: E402  (bpy import order)
import sys

# Blender-only module guard
try:
    import bpy  # type: ignore[import]
except ModuleNotFoundError:
    bpy = None  # type: ignore[assignment]

from typing import Any, Dict, List, Optional

_ALLOWED_PRIMITIVES = frozenset(
    {"CUBE", "UV_SPHERE", "ICO_SPHERE", "CYLINDER", "CONE", "TORUS"}
)
_ALLOWED_MODES = frozenset({"OBJECT", "EDIT"})
_STEP_KINDS = frozenset(
    {
        "ADD_MESH",
        "SET_MODE",
        "TRANSLATE",
        "SCALE",
        "ROTATE",
        "BEVEL",
        "INSET",
        "EXTRUDE_REGION",
        "SET_CAMERA",
        "SET_MATERIAL",
        "DELETE_ALL",
        "SELECT_ALL",
    }
)


# ---------------------------------------------------------------------------
# Scene reset
# ---------------------------------------------------------------------------


def reset_scene(initial_scene: Dict[str, Any]) -> None:
    """Hard reset to factory empty, then populate seed objects from initial_scene dict."""
    bpy.ops.wm.read_factory_settings(use_empty=True)

    for seed in initial_scene.get("objects", []):
        _seed_object(seed)

    active_name = initial_scene.get("active") or initial_scene.get("active_object")
    if active_name and active_name in bpy.data.objects:
        bpy.context.view_layer.objects.active = bpy.data.objects[active_name]


def _seed_object(seed: Dict[str, Any]) -> None:
    primitive = str(seed.get("primitive", "CUBE")).upper()
    loc = tuple(float(v) for v in seed.get("location", [0.0, 0.0, 0.0]))
    rot = tuple(float(v) for v in seed.get("rotation", [0.0, 0.0, 0.0]))
    scale = tuple(float(v) for v in seed.get("scale", [1.0, 1.0, 1.0]))

    if primitive == "CUBE":
        bpy.ops.mesh.primitive_cube_add(location=loc, rotation=rot, scale=scale)
    elif primitive == "UV_SPHERE":
        bpy.ops.mesh.primitive_uv_sphere_add(location=loc, rotation=rot, scale=scale)
    elif primitive == "ICO_SPHERE":
        bpy.ops.mesh.primitive_ico_sphere_add(location=loc, rotation=rot, scale=scale)
    elif primitive == "CYLINDER":
        bpy.ops.mesh.primitive_cylinder_add(location=loc, rotation=rot, scale=scale)
    elif primitive == "CONE":
        bpy.ops.mesh.primitive_cone_add(location=loc, rotation=rot, scale=scale)
    elif primitive == "TORUS":
        bpy.ops.mesh.primitive_torus_add(location=loc, rotation=rot)
    else:
        sys.stderr.write(f"[dispatcher] Unknown seed primitive {primitive!r}, skipping\n")
        return

    obj = bpy.context.active_object
    if obj and seed.get("name"):
        obj.name = seed["name"]
        if obj.data:
            obj.data.name = seed["name"]


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------


def execute_normalized_steps(steps: List[Dict[str, Any]]) -> None:
    """Execute a list of normalized step dicts. Raises on first error."""
    for step in steps:
        _dispatch_one_step(step)


def _dispatch_one_step(step: Dict[str, Any]) -> None:
    kind = str(step.get("kind", "")).upper()
    args = step.get("args", {}) or {}

    if kind not in _STEP_KINDS:
        raise ValueError(f"Unknown step kind {kind!r}")

    if kind == "ADD_MESH":
        _add_mesh(args)
    elif kind == "SET_MODE":
        _set_mode(args)
    elif kind == "TRANSLATE":
        bpy.ops.transform.translate(value=tuple(args["value"]))
    elif kind == "SCALE":
        bpy.ops.transform.resize(value=tuple(args["value"]))
    elif kind == "ROTATE":
        bpy.ops.transform.rotate(
            value=float(args["value"]),
            orient_axis=str(args.get("orient_axis", "Z")),
        )
    elif kind == "BEVEL":
        bpy.ops.mesh.bevel(
            offset=float(args.get("offset", 0.0)),
            segments=int(args.get("segments", 1)),
            profile=float(args.get("profile", 0.5)),
        )
    elif kind == "INSET":
        bpy.ops.mesh.inset(
            thickness=float(args.get("thickness", 0.0)),
            depth=float(args.get("depth", 0.0)),
        )
    elif kind == "EXTRUDE_REGION":
        translate = args.get("translate", [0.0, 0.0, 0.0])
        bpy.ops.mesh.extrude_region_move(
            TRANSFORM_OT_translate={"value": tuple(translate)}
        )
    elif kind == "SET_CAMERA":
        _set_camera(args)
    elif kind == "SET_MATERIAL":
        _set_material(args)
    elif kind == "DELETE_ALL":
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete()
    elif kind == "SELECT_ALL":
        action = str(args.get("action", "SELECT")).upper()
        bpy.ops.object.select_all(action=action)


def _add_mesh(args: Dict[str, Any]) -> None:
    primitive = str(args.get("primitive", "CUBE")).upper()
    loc = tuple(float(v) for v in args.get("location", [0.0, 0.0, 0.0]))
    rot = tuple(float(v) for v in args.get("rotation", [0.0, 0.0, 0.0]))
    scale = tuple(float(v) for v in args.get("scale", [1.0, 1.0, 1.0]))

    if primitive == "CUBE":
        kwargs: Dict[str, Any] = {"location": loc, "rotation": rot, "scale": scale}
        if "size" in args:
            kwargs["size"] = float(args["size"])
        bpy.ops.mesh.primitive_cube_add(**kwargs)
    elif primitive == "UV_SPHERE":
        kwargs = {"location": loc, "rotation": rot, "scale": scale}
        if "radius" in args:
            kwargs["radius"] = float(args["radius"])
        if "segments" in args:
            kwargs["segments"] = int(args["segments"])
        if "ring_count" in args:
            kwargs["ring_count"] = int(args["ring_count"])
        bpy.ops.mesh.primitive_uv_sphere_add(**kwargs)
    elif primitive == "ICO_SPHERE":
        kwargs = {"location": loc, "rotation": rot, "scale": scale}
        if "radius" in args:
            kwargs["radius"] = float(args["radius"])
        if "subdivisions" in args:
            kwargs["subdivisions"] = int(args["subdivisions"])
        bpy.ops.mesh.primitive_ico_sphere_add(**kwargs)
    elif primitive == "CYLINDER":
        kwargs = {"location": loc, "rotation": rot, "scale": scale}
        if "radius" in args:
            kwargs["radius"] = float(args["radius"])
        if "depth" in args:
            kwargs["depth"] = float(args["depth"])
        if "vertices" in args:
            kwargs["vertices"] = int(args["vertices"])
        bpy.ops.mesh.primitive_cylinder_add(**kwargs)
    elif primitive == "CONE":
        kwargs = {"location": loc, "rotation": rot, "scale": scale}
        if "radius1" in args:
            kwargs["radius1"] = float(args["radius1"])
        if "radius2" in args:
            kwargs["radius2"] = float(args["radius2"])
        if "depth" in args:
            kwargs["depth"] = float(args["depth"])
        if "vertices" in args:
            kwargs["vertices"] = int(args["vertices"])
        bpy.ops.mesh.primitive_cone_add(**kwargs)
    elif primitive == "TORUS":
        kwargs = {"location": loc, "rotation": rot}
        if "major_radius" in args:
            kwargs["major_radius"] = float(args["major_radius"])
        if "minor_radius" in args:
            kwargs["minor_radius"] = float(args["minor_radius"])
        if "major_segments" in args:
            kwargs["major_segments"] = int(args["major_segments"])
        if "minor_segments" in args:
            kwargs["minor_segments"] = int(args["minor_segments"])
        bpy.ops.mesh.primitive_torus_add(**kwargs)
    else:
        raise ValueError(f"Unsupported primitive {primitive!r}")


def _set_mode(args: Dict[str, Any]) -> None:
    mode = str(args.get("mode", "OBJECT")).upper()
    if mode not in _ALLOWED_MODES:
        raise ValueError(f"Unsupported mode {mode!r}")
    bpy.ops.object.mode_set(mode=mode)


def _set_camera(args: Dict[str, Any]) -> None:
    name = str(args.get("name", "")).strip()
    if name not in bpy.data.objects:
        raise ValueError(f"Camera object {name!r} not found in scene")
    obj = bpy.data.objects[name]
    if obj.type != "CAMERA":
        raise ValueError(f"Object {name!r} is not a camera")
    bpy.context.scene.camera = obj


def _set_material(args: Dict[str, Any]) -> None:
    obj = bpy.context.active_object
    if obj is None or obj.type != "MESH":
        raise ValueError("SET_MATERIAL requires an active mesh object")

    mat_name = args.get("name")
    base_color = args.get("base_color")

    if mat_name and mat_name in bpy.data.materials:
        mat = bpy.data.materials[mat_name]
    else:
        mat = bpy.data.materials.new(name=mat_name or "EvalMaterial")
        mat.use_nodes = True

    if base_color:
        _set_principled_base_color(mat, base_color)

    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


def _set_principled_base_color(mat: Any, color: List[float]) -> None:
    if not mat.use_nodes:
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        for node in nodes:
            if node.type == "BSDF_PRINCIPLED":
                bsdf = node
                break
    if bsdf is None:
        return
    # Pad to RGBA
    rgba = list(color) + [1.0] * (4 - len(color))
    bsdf.inputs["Base Color"].default_value = rgba[:4]
