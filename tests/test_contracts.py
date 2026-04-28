"""Tests for nalana_eval/contracts.py."""
from __future__ import annotations

import json
import pytest

from nalana_eval.contracts import (
    ALLOWED_MODES,
    ALLOWED_PRIMITIVES,
    ALLOWED_ROTATE_AXES,
    canonicalize_step,
    compute_normalization_signature,
    normalize_legacy_operation,
    normalize_model_output,
    normalize_typed_command,
)
from nalana_eval.schema import NormalizedStep, OutputContract, StepKind


# ---------------------------------------------------------------------------
# ALLOWED_PRIMITIVES is a frozenset (constant reference, not magic strings)
# ---------------------------------------------------------------------------

def test_allowed_primitives_type():
    assert isinstance(ALLOWED_PRIMITIVES, frozenset)
    assert "CUBE" in ALLOWED_PRIMITIVES
    assert "UV_SPHERE" in ALLOWED_PRIMITIVES
    assert "TORUS" in ALLOWED_PRIMITIVES


def test_allowed_modes_type():
    assert isinstance(ALLOWED_MODES, frozenset)
    assert "OBJECT" in ALLOWED_MODES
    assert "EDIT" in ALLOWED_MODES


# ---------------------------------------------------------------------------
# canonicalize_step: ADD_MESH
# ---------------------------------------------------------------------------

def test_canonicalize_add_mesh_cube():
    step = canonicalize_step("ADD_MESH", {"primitive": "CUBE"})
    assert step.kind == StepKind.ADD_MESH
    assert step.args["primitive"] == "CUBE"


def test_canonicalize_add_mesh_cube_lowercase():
    step = canonicalize_step("ADD_MESH", {"primitive": "cube"})
    assert step.args["primitive"] == "CUBE"


def test_canonicalize_add_mesh_sphere_with_radius():
    step = canonicalize_step("ADD_MESH", {"primitive": "UV_SPHERE", "radius": 2.0, "segments": 32})
    assert step.args["radius"] == 2.0
    assert step.args["segments"] == 32


def test_canonicalize_add_mesh_sphere_segments_too_large():
    with pytest.raises(ValueError, match="exceeds maximum"):
        canonicalize_step("ADD_MESH", {"primitive": "UV_SPHERE", "segments": 257})


def test_canonicalize_add_mesh_sphere_radius_zero():
    with pytest.raises(ValueError, match="below minimum"):
        canonicalize_step("ADD_MESH", {"primitive": "UV_SPHERE", "radius": 0.0})


def test_canonicalize_add_mesh_unsupported_primitive():
    with pytest.raises(ValueError, match="Unsupported primitive"):
        canonicalize_step("ADD_MESH", {"primitive": "MONKEY"})


def test_canonicalize_add_mesh_unknown_arg():
    with pytest.raises(ValueError, match="does not allow arguments"):
        canonicalize_step("ADD_MESH", {"primitive": "CUBE", "bad_param": 1})


def test_canonicalize_add_mesh_ico_sphere():
    step = canonicalize_step("ADD_MESH", {"primitive": "ICO_SPHERE", "subdivisions": 4, "radius": 1.5})
    assert step.args["subdivisions"] == 4


def test_canonicalize_add_mesh_ico_sphere_subdivisions_out_of_range():
    with pytest.raises(ValueError):
        canonicalize_step("ADD_MESH", {"primitive": "ICO_SPHERE", "subdivisions": 9})


def test_canonicalize_add_mesh_torus():
    step = canonicalize_step(
        "ADD_MESH",
        {"primitive": "TORUS", "major_radius": 1.0, "minor_radius": 0.25, "major_segments": 48},
    )
    assert step.args["major_segments"] == 48


def test_canonicalize_add_mesh_cylinder():
    step = canonicalize_step("ADD_MESH", {"primitive": "CYLINDER", "vertices": 8, "radius": 1.0, "depth": 2.0})
    assert step.args["vertices"] == 8


def test_canonicalize_add_mesh_cone():
    step = canonicalize_step(
        "ADD_MESH", {"primitive": "CONE", "vertices": 6, "radius1": 1.0, "radius2": 0.0, "depth": 2.0}
    )
    assert step.args["radius2"] == 0.0


# ---------------------------------------------------------------------------
# canonicalize_step: other kinds
# ---------------------------------------------------------------------------

def test_canonicalize_set_mode_object():
    step = canonicalize_step("SET_MODE", {"mode": "OBJECT"})
    assert step.args["mode"] == "OBJECT"


def test_canonicalize_set_mode_edit():
    step = canonicalize_step("SET_MODE", {"mode": "EDIT"})
    assert step.args["mode"] == "EDIT"


def test_canonicalize_set_mode_edit_variant():
    step = canonicalize_step("SET_MODE", {"mode": "EDIT_MODE"})
    assert step.args["mode"] == "EDIT"


def test_canonicalize_set_mode_unsupported():
    with pytest.raises(ValueError, match="Unsupported mode"):
        canonicalize_step("SET_MODE", {"mode": "POSE"})


def test_canonicalize_translate():
    step = canonicalize_step("TRANSLATE", {"value": [1.0, 2.0, 3.0]})
    assert step.args["value"] == [1.0, 2.0, 3.0]


def test_canonicalize_translate_wrong_length():
    with pytest.raises(ValueError):
        canonicalize_step("TRANSLATE", {"value": [1.0, 2.0]})


def test_canonicalize_scale():
    step = canonicalize_step("SCALE", {"value": [2.0, 2.0, 2.0]})
    assert step.args["value"] == [2.0, 2.0, 2.0]


def test_canonicalize_rotate():
    step = canonicalize_step("ROTATE", {"value": 1.5707, "orient_axis": "Z"})
    assert step.args["orient_axis"] == "Z"


def test_canonicalize_rotate_bad_axis():
    with pytest.raises(ValueError, match="Unsupported rotate axis"):
        canonicalize_step("ROTATE", {"value": 1.0, "orient_axis": "W"})


def test_canonicalize_bevel():
    step = canonicalize_step("BEVEL", {"offset": 0.1, "segments": 2})
    assert step.args["segments"] == 2


def test_canonicalize_bevel_segments_too_large():
    with pytest.raises(ValueError):
        canonicalize_step("BEVEL", {"offset": 0.1, "segments": 33})


def test_canonicalize_inset():
    step = canonicalize_step("INSET", {"thickness": 0.1})
    assert step.args["thickness"] == 0.1


def test_canonicalize_set_material():
    step = canonicalize_step("SET_MATERIAL", {"base_color": [1.0, 0.0, 0.0, 1.0]})
    assert step.args["base_color"] == [1.0, 0.0, 0.0, 1.0]


def test_canonicalize_set_material_empty_fails():
    with pytest.raises(ValueError, match="requires at least one"):
        canonicalize_step("SET_MATERIAL", {})


def test_canonicalize_delete_all():
    step = canonicalize_step("DELETE_ALL", {})
    assert step.kind == StepKind.DELETE_ALL


def test_canonicalize_select_all():
    step = canonicalize_step("SELECT_ALL", {"action": "SELECT"})
    assert step.args["action"] == "SELECT"


# ---------------------------------------------------------------------------
# Dangerous operations are blocked
# ---------------------------------------------------------------------------

def test_blocked_op_quit_blender():
    with pytest.raises(ValueError, match="Blocked operation"):
        normalize_legacy_operation({"op": "bpy.ops.wm.quit_blender", "params": {}})


def test_blocked_op_save_mainfile():
    with pytest.raises(ValueError, match="Blocked operation"):
        normalize_legacy_operation({"op": "bpy.ops.wm.save_mainfile", "params": {}})


def test_blocked_op_script_run():
    with pytest.raises(ValueError, match="Blocked operation"):
        normalize_legacy_operation({"op": "bpy.ops.script.python_file_run", "params": {}})


# ---------------------------------------------------------------------------
# normalize_legacy_operation: three contract flavors
# ---------------------------------------------------------------------------

def test_normalize_legacy_cube():
    step = normalize_legacy_operation({"op": "bpy.ops.mesh.primitive_cube_add", "params": {}})
    assert step.kind == StepKind.ADD_MESH
    assert step.args["primitive"] == "CUBE"


def test_normalize_legacy_mode_set():
    step = normalize_legacy_operation({"op": "bpy.ops.object.mode_set", "params": {"mode": "EDIT"}})
    assert step.args["mode"] == "EDIT"


def test_normalize_legacy_translate():
    step = normalize_legacy_operation(
        {"op": "bpy.ops.transform.translate", "params": {"value": [0.0, 1.0, 0.0]}}
    )
    assert step.kind == StepKind.TRANSLATE


def test_normalize_legacy_unsupported_op():
    with pytest.raises(ValueError, match="Unsupported legacy operation"):
        normalize_legacy_operation({"op": "bpy.ops.object.unknown_op", "params": {}})


def test_normalize_legacy_extrude_with_translate():
    step = normalize_legacy_operation(
        {
            "op": "bpy.ops.mesh.extrude_region_move",
            "params": {"TRANSFORM_OT_translate": {"value": [0.0, 0.0, 1.0]}},
        }
    )
    assert step.kind == StepKind.EXTRUDE_REGION
    assert step.args["translate"] == [0.0, 0.0, 1.0]


def test_normalize_legacy_delete():
    step = normalize_legacy_operation({"op": "bpy.ops.object.delete", "params": {}})
    assert step.kind == StepKind.DELETE_ALL


# ---------------------------------------------------------------------------
# normalize_typed_command
# ---------------------------------------------------------------------------

def test_normalize_typed_add_mesh():
    steps = normalize_typed_command({"type": "ADD_MESH", "args": {"primitive": "UV_SPHERE", "radius": 1.0}})
    assert len(steps) == 1
    assert steps[0].kind == StepKind.ADD_MESH


def test_normalize_typed_transform_multi():
    steps = normalize_typed_command(
        {"type": "TRANSFORM", "args": {"translate": [1.0, 0.0, 0.0], "scale": [2.0, 2.0, 2.0]}}
    )
    assert len(steps) == 2
    kinds = {s.kind for s in steps}
    assert StepKind.TRANSLATE in kinds
    assert StepKind.SCALE in kinds


def test_normalize_typed_transform_empty_fails():
    with pytest.raises(ValueError, match="at least one"):
        normalize_typed_command({"type": "TRANSFORM", "args": {}})


def test_normalize_typed_edit_mesh_bevel():
    steps = normalize_typed_command({"type": "EDIT_MESH", "args": {"operation": "BEVEL", "offset": 0.05}})
    assert steps[0].kind == StepKind.BEVEL


def test_normalize_typed_edit_mesh_bad_op():
    with pytest.raises(ValueError, match="Unsupported EDIT_MESH"):
        normalize_typed_command({"type": "EDIT_MESH", "args": {"operation": "SUBDIVIDE"}})


def test_normalize_typed_set_material():
    steps = normalize_typed_command({"type": "SET_MATERIAL", "args": {"base_color": [0.0, 0.0, 1.0]}})
    assert steps[0].kind == StepKind.SET_MATERIAL


def test_normalize_typed_unsupported():
    with pytest.raises(ValueError, match="Unsupported typed benchmark command"):
        normalize_typed_command({"type": "FAKE_COMMAND", "args": {}})


# ---------------------------------------------------------------------------
# normalize_model_output: contract auto-detection
# ---------------------------------------------------------------------------

def test_normalize_model_output_normalized_contract():
    raw = json.dumps([{"kind": "ADD_MESH", "args": {"primitive": "CUBE"}}])
    steps, contract = normalize_model_output(raw)
    assert contract == OutputContract.NORMALIZED
    assert len(steps) == 1


def test_normalize_model_output_legacy_contract():
    raw = json.dumps([{"op": "bpy.ops.mesh.primitive_cube_add", "params": {}}])
    steps, contract = normalize_model_output(raw)
    assert contract == OutputContract.LEGACY_OPS


def test_normalize_model_output_typed_contract():
    raw = json.dumps([{"type": "ADD_MESH", "args": {"primitive": "CUBE"}}])
    steps, contract = normalize_model_output(raw)
    assert contract == OutputContract.TYPED_COMMANDS


def test_normalize_model_output_with_commands_wrapper():
    raw = json.dumps({"commands": [{"kind": "ADD_MESH", "args": {"primitive": "CUBE"}}]})
    steps, contract = normalize_model_output(raw)
    assert contract == OutputContract.NORMALIZED
    assert len(steps) == 1


def test_normalize_model_output_empty_list():
    steps, contract = normalize_model_output("[]")
    assert steps == []
    assert contract == OutputContract.AUTO


def test_normalize_model_output_invalid_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        normalize_model_output("not json at all")


def test_normalize_model_output_mixed_contract_fails():
    raw = json.dumps([
        {"kind": "ADD_MESH", "args": {"primitive": "CUBE"}},
        {"op": "bpy.ops.object.mode_set", "params": {}},
    ])
    with pytest.raises(ValueError, match="consistently"):
        normalize_model_output(raw)


def test_normalize_model_output_blocked_op_in_legacy():
    raw = json.dumps([{"op": "bpy.ops.wm.quit_blender", "params": {}}])
    with pytest.raises(ValueError, match="Blocked"):
        normalize_model_output(raw)


# ---------------------------------------------------------------------------
# compute_normalization_signature
# ---------------------------------------------------------------------------

def test_compute_signature_stable():
    steps = [
        canonicalize_step("ADD_MESH", {"primitive": "CUBE"}),
        canonicalize_step("SET_MODE", {"mode": "EDIT"}),
    ]
    sig1 = compute_normalization_signature(steps)
    sig2 = compute_normalization_signature(steps)
    assert sig1 == sig2
    assert len(sig1) == 64  # sha256 hex


def test_compute_signature_differs_for_different_steps():
    steps_a = [canonicalize_step("ADD_MESH", {"primitive": "CUBE"})]
    steps_b = [canonicalize_step("ADD_MESH", {"primitive": "UV_SPHERE"})]
    assert compute_normalization_signature(steps_a) != compute_normalization_signature(steps_b)


def test_compute_signature_empty():
    sig = compute_normalization_signature([])
    assert len(sig) == 64
