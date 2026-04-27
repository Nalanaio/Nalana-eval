"""Programmatic v3.0 test case generator.

Produces TestSuite-compatible JSON by combining primitive types,
colors, and sizes across TaskFamily templates.

Usage:
    python fixtures/synthetic/generate_cases.py --out fixtures/synthetic/generated.json
"""
from __future__ import annotations

import argparse
import json
import sys
from itertools import product
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Templates per TaskFamily
# ---------------------------------------------------------------------------

_PRIMITIVES = ["CUBE", "UV_SPHERE", "ICO_SPHERE", "CYLINDER", "CONE", "TORUS"]

_COLORS = {
    "red":    [1.0, 0.0, 0.0, 1.0],
    "green":  [0.0, 0.8, 0.0, 1.0],
    "blue":   [0.0, 0.0, 1.0, 1.0],
    "yellow": [1.0, 1.0, 0.0, 1.0],
    "white":  [1.0, 1.0, 1.0, 1.0],
}

_SIZES = {
    "small":  {"radius": 0.5, "size": [0.8, 0.8, 0.8], "bbox_min": [0.8, 0.8, 0.8], "bbox_max": [1.2, 1.2, 1.2]},
    "medium": {"radius": 1.0, "size": [1.8, 1.8, 1.8], "bbox_min": [1.5, 1.5, 1.5], "bbox_max": [2.5, 2.5, 2.5]},
    "large":  {"radius": 2.0, "size": [3.5, 3.5, 3.5], "bbox_min": [3.5, 3.5, 3.5], "bbox_max": [4.5, 4.5, 4.5]},
}

_PRIM_PROMPT_NAMES = {
    "CUBE": "cube", "UV_SPHERE": "sphere", "ICO_SPHERE": "icosphere",
    "CYLINDER": "cylinder", "CONE": "cone", "TORUS": "torus",
}

_COUNTER: Dict[str, int] = {}


def _next_id(prefix: str) -> str:
    _COUNTER[prefix] = _COUNTER.get(prefix, 0) + 1
    return f"{prefix}-{_COUNTER[prefix]:03d}"


def _primitive_creation_case(primitive: str) -> Dict[str, Any]:
    name = _PRIM_PROMPT_NAMES[primitive]
    case_id = _next_id("SYN-OBJ")
    return {
        "fixture_version": "3.0",
        "id": case_id,
        "category": "Object Creation",
        "difficulty": "Short",
        "task_family": "primitive_creation",
        "prompt_variants": [
            f"Add a {name} to the scene",
            f"Create a {name}",
            f"Please add a {name}",
        ],
        "initial_scene": {"mode": "OBJECT", "objects": []},
        "hard_constraints": {
            "mesh_object_count": {"minimum": 1},
            "required_object_types": ["MESH"],
        },
        "topology_policy": {"manifold_required": False, "quad_ratio_min": 0.0},
        "soft_constraints": [
            {"name": "single object", "metric": "total_mesh_objects", "direction": "exact",
             "target": 1.0, "tolerance": 0.0, "weight": 0.5},
        ],
        "style_intent": {"explicit": False, "concept": name, "acceptable_styles": ["geometric"]},
        "judge_policy": "skip",
        "artifact_policy": {"require_screenshot": True, "write_scene_stats": True},
    }


def _parameterized_primitive_case(primitive: str, size_label: str) -> Dict[str, Any]:
    name = _PRIM_PROMPT_NAMES[primitive]
    sz = _SIZES[size_label]
    case_id = _next_id("SYN-PAR")
    radius_phrase = f"with radius {sz['radius']} meter{'s' if sz['radius'] != 1 else ''}"
    size_phrase = f"about {sz['radius'] * 2} meters wide"
    return {
        "fixture_version": "3.0",
        "id": case_id,
        "category": "Object Creation",
        "difficulty": "Medium",
        "task_family": "parameterized_primitive_creation",
        "prompt_variants": [
            f"Add a {name} {radius_phrase}",
            f"Create a {size_label} {name}, {size_phrase}",
            f"Make a {name} with approximate radius {sz['radius']}m",
        ],
        "initial_scene": {"mode": "OBJECT", "objects": []},
        "hard_constraints": {
            "mesh_object_count": {"minimum": 1},
            "bounding_boxes": [
                {
                    "target": "__scene__",
                    "size_range": {
                        "minimum": sz["bbox_min"],
                        "maximum": sz["bbox_max"],
                    },
                }
            ],
        },
        "topology_policy": {"manifold_required": False, "quad_ratio_min": 0.0},
        "soft_constraints": [],
        "style_intent": {"explicit": False, "concept": name, "acceptable_styles": ["geometric"]},
        "judge_policy": "skip",
        "artifact_policy": {"require_screenshot": True, "write_scene_stats": True},
    }


def _material_color_case(primitive: str, color_name: str) -> Dict[str, Any]:
    name = _PRIM_PROMPT_NAMES[primitive]
    color = _COLORS[color_name]
    case_id = _next_id("SYN-MAT")
    return {
        "fixture_version": "3.0",
        "id": case_id,
        "category": "Materials & Shading",
        "difficulty": "Short",
        "task_family": "material_color_assignment",
        "prompt_variants": [
            f"Make the {name} {color_name}",
            f"Apply a {color_name} material to the {name}",
            f"Color the {name} {color_name}",
        ],
        "initial_scene": {
            "mode": "OBJECT",
            "objects": [{"primitive": primitive, "name": primitive.capitalize()}],
        },
        "hard_constraints": {
            "mesh_object_count": {"minimum": 1},
            "materials": [{"target": "*", "base_color": color, "tolerance": 0.25}],
        },
        "topology_policy": {"manifold_required": False, "quad_ratio_min": 0.0},
        "soft_constraints": [],
        "style_intent": {"explicit": False, "acceptable_styles": ["geometric"]},
        "judge_policy": "skip",
        "artifact_policy": {"require_screenshot": True, "write_scene_stats": True},
    }


# ---------------------------------------------------------------------------
# Generator entry point
# ---------------------------------------------------------------------------


def generate(max_cases: int = 200) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []

    # primitive_creation: one per primitive
    for prim in _PRIMITIVES:
        cases.append(_primitive_creation_case(prim))

    # parameterized: sphere+cylinder in small/medium/large
    for prim in ["UV_SPHERE", "CYLINDER", "CONE"]:
        for sz in ["small", "medium", "large"]:
            cases.append(_parameterized_primitive_case(prim, sz))

    # material: cube + sphere × 5 colors
    for prim in ["CUBE", "UV_SPHERE"]:
        for color in _COLORS:
            cases.append(_material_color_case(prim, color))

    return cases[:max_cases]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic v3.0 test cases")
    parser.add_argument("--out", default="fixtures/synthetic/generated.json")
    parser.add_argument("--max", type=int, default=200)
    args = parser.parse_args()

    cases = generate(args.max)
    suite = {
        "suite_id": "synthetic-v3",
        "fixture_version": "3.0",
        "cases": cases,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(suite, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {len(cases)} cases → {out}")


if __name__ == "__main__":
    main()
