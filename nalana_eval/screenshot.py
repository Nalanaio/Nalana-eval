"""Screenshot rendering.

render_scene_to_png / place_camera_iso / setup_workbench_lighting:
    Run inside Blender process (bpy only, no PIL).

make_thumbnail / make_fallback_png:
    Called from main process after worker returns the PNG path (PIL required).
"""
import os
from typing import Any, Optional, Tuple

try:
    import bpy  # type: ignore[import]
    from mathutils import Vector  # type: ignore[import]
except ModuleNotFoundError:
    bpy = Vector = None  # type: ignore[assignment]

# Minimal valid 1×1 black PNG for environments without PIL
_MINIMAL_PNG_BYTES = bytes([
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
    0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
    0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
    0xde, 0x00, 0x00, 0x00, 0x0c, 0x49, 0x44, 0x41,
    0x54, 0x78, 0x9c, 0x62, 0xf8, 0x0f, 0x00, 0x00,
    0x01, 0x01, 0x00, 0x05, 0x18, 0xd8, 0x4e, 0x00,
    0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae,
    0x42, 0x60, 0x82,
])


# ---------------------------------------------------------------------------
# Blender-side: render
# ---------------------------------------------------------------------------


def render_scene_to_png(output_path: str, resolution: Tuple[int, int] = (800, 600)) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = resolution[0]
    scene.render.resolution_y = resolution[1]
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = output_path

    place_camera_iso(scene)
    setup_workbench_lighting(scene)

    bpy.ops.render.render(write_still=True)


def place_camera_iso(scene: Any) -> None:
    """Place an isometric-style camera based on merged bbox of all mesh objects."""
    mesh_objects = [o for o in bpy.data.objects if o.type == "MESH"]

    cam = _ensure_camera(scene)

    if not mesh_objects:
        cam.location = Vector((5.0, -5.0, 3.5))
        cam.rotation_euler = _look_at(Vector((5.0, -5.0, 3.5)), Vector((0.0, 0.0, 0.0)))
        return

    all_corners = [
        obj.matrix_world @ Vector(c) for obj in mesh_objects for c in obj.bound_box
    ]
    center = sum(all_corners, Vector()) / len(all_corners)
    max_dim = max(
        max(c.x for c in all_corners) - min(c.x for c in all_corners),
        max(c.y for c in all_corners) - min(c.y for c in all_corners),
        max(c.z for c in all_corners) - min(c.z for c in all_corners),
        0.1,
    )
    distance = max_dim * 2.5
    cam.location = center + Vector((distance, -distance, distance * 0.7))
    cam.rotation_euler = _look_at(cam.location, center)


def _look_at(cam_loc: Any, target: Any) -> Any:
    direction = target - cam_loc
    return direction.to_track_quat("-Z", "Y").to_euler()


def _ensure_camera(scene: Any) -> Any:
    for obj in bpy.data.objects:
        if obj.type == "CAMERA":
            scene.camera = obj
            return obj
    cam_data = bpy.data.cameras.new("EvalCamera")
    cam_obj = bpy.data.objects.new("EvalCamera", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    scene.camera = cam_obj
    return cam_obj


def setup_workbench_lighting(scene: Any) -> None:
    """Configure Workbench studio lighting for consistent rendering."""
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "MATERIAL"
    shading.show_specular_highlight = True


# ---------------------------------------------------------------------------
# Main-process side: thumbnail + fallback (PIL, not called from Blender worker)
# ---------------------------------------------------------------------------


def make_thumbnail(png_path: str, size: Tuple[int, int] = (512, 384)) -> str:
    """Create a thumbnail of png_path; returns thumbnail path."""
    from PIL import Image  # noqa: PLC0415

    img = Image.open(png_path)
    img.thumbnail(size, Image.LANCZOS)
    thumb_path = png_path.replace(".png", "_thumb.png")
    img.save(thumb_path, format="PNG")
    return thumb_path


def make_fallback_png(output_path: str, case_id: str = "", failure_class: str = "") -> None:
    """Write a placeholder PNG for failed/skipped cases. Uses PIL if available."""
    try:
        from PIL import Image, ImageDraw  # noqa: PLC0415

        img = Image.new("RGB", (800, 600), color=(10, 10, 10))
        draw = ImageDraw.Draw(img)
        draw.text((20, 20), f"CASE: {case_id}", fill=(220, 220, 220))
        draw.text((20, 60), f"STATUS: {failure_class or 'no screenshot'}", fill=(220, 80, 80))
        img.save(output_path, format="PNG")
    except Exception:
        with open(output_path, "wb") as fh:
            fh.write(_MINIMAL_PNG_BYTES)
