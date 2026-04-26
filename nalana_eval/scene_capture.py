"""Capture scene statistics as a plain dict. Runs inside Blender; stdlib + bpy ONLY."""
from typing import Any, Dict, List, Optional

try:
    import bpy  # type: ignore[import]
    import bmesh  # type: ignore[import]
    from mathutils import Vector  # type: ignore[import]
except ModuleNotFoundError:
    bpy = bmesh = Vector = None  # type: ignore[assignment]


def capture() -> Dict[str, Any]:
    """Return scene statistics dict. Main process calls SceneSnapshot.model_validate(result)."""
    mesh_objects: List[Dict[str, Any]] = []
    all_bbox_corners: List[Any] = []
    total_verts = 0
    total_faces = 0
    total_quad_faces = 0
    all_manifold = True

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue

        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)

            face_sizes: Dict[str, int] = {}
            for face in bm.faces:
                n = str(len(face.verts))
                face_sizes[n] = face_sizes.get(n, 0) + 1

            v_count = len(bm.verts)
            e_count = len(bm.edges)
            f_count = len(bm.faces)
            quad_faces = face_sizes.get("4", 0)
            manifold = all(edge.is_manifold for edge in bm.edges) if bm.edges else True
        finally:
            bm.free()

        # World-space bounding box
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        bbox_min = [min(c[i] for c in corners) for i in range(3)]
        bbox_max = [max(c[i] for c in corners) for i in range(3)]
        all_bbox_corners.extend(corners)

        materials = _capture_materials(obj)

        total_verts += v_count
        total_faces += f_count
        total_quad_faces += quad_faces
        if not manifold:
            all_manifold = False

        mesh_objects.append(
            {
                "name": obj.name,
                "object_type": "MESH",
                "vertex_count": v_count,
                "edge_count": e_count,
                "face_count": f_count,
                "face_sizes": face_sizes,
                "manifold": manifold,
                "bbox_min": bbox_min,
                "bbox_max": bbox_max,
                "location": list(obj.location),
                "rotation": list(obj.rotation_euler),
                "scale": list(obj.scale),
                "materials": materials,
            }
        )

    if all_bbox_corners:
        scene_bbox_min = [min(c[i] for c in all_bbox_corners) for i in range(3)]
        scene_bbox_max = [max(c[i] for c in all_bbox_corners) for i in range(3)]
    else:
        scene_bbox_min = [0.0, 0.0, 0.0]
        scene_bbox_max = [0.0, 0.0, 0.0]

    quad_ratio = total_quad_faces / total_faces if total_faces > 0 else 0.0
    active_obj = bpy.context.view_layer.objects.active

    return {
        "active_object": active_obj.name if active_obj else None,
        "total_objects": len(list(bpy.data.objects)),
        "total_mesh_objects": len(mesh_objects),
        "total_vertices": total_verts,
        "total_faces": total_faces,
        "quad_ratio": quad_ratio,
        "manifold": all_manifold,
        "bbox_min": scene_bbox_min,
        "bbox_max": scene_bbox_max,
        "mesh_objects": mesh_objects,
    }


def _capture_materials(obj: Any) -> List[Dict[str, Any]]:
    result = []
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            continue
        if mat.use_nodes:
            base_color = _get_principled_base_color(mat)
        else:
            base_color = list(mat.diffuse_color[:4])
        result.append({"name": mat.name, "base_color": base_color})
    return result


def _get_principled_base_color(mat: Any) -> List[float]:
    nodes = mat.node_tree.nodes if mat.node_tree else []
    for node in nodes:
        if node.type == "BSDF_PRINCIPLED":
            color = node.inputs["Base Color"].default_value
            return list(color[:4])
    return [0.8, 0.8, 0.8, 1.0]
