"""Programmatic v3.0 test case generator.

Produces TestSuite-compatible JSON combining primitives × colors × sizes.

Default output: fixtures/synthetic/generated_primitive_cases.json (50 cases)

Usage:
    python fixtures/synthetic/generate_cases.py
    python fixtures/synthetic/generate_cases.py --out path/to/out.json --max 100
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

_PRIMITIVES = ["CUBE", "UV_SPHERE", "CYLINDER", "CONE", "TORUS"]

_PRIM_NAME = {
    "CUBE": "cube",
    "UV_SPHERE": "sphere",
    "CYLINDER": "cylinder",
    "CONE": "cone",
    "TORUS": "torus",
}

_COLORS: Dict[str, List[float]] = {
    "red":    [1.0, 0.0, 0.0, 1.0],
    "blue":   [0.0, 0.0, 1.0, 1.0],
    "green":  [0.0, 0.8, 0.0, 1.0],
    "yellow": [1.0, 1.0, 0.0, 1.0],
    "white":  [1.0, 1.0, 1.0, 1.0],
    "black":  [0.0, 0.0, 0.0, 1.0],
}

_SIZES = {
    "small":  {"radius": 0.5, "bbox_min": [0.8, 0.8, 0.8],  "bbox_max": [1.2, 1.2, 1.2]},
    "medium": {"radius": 1.0, "bbox_min": [1.5, 1.5, 1.5],  "bbox_max": [2.5, 2.5, 2.5]},
    "large":  {"radius": 2.0, "bbox_min": [3.5, 3.5, 3.5],  "bbox_max": [4.5, 4.5, 4.5]},
}

_counter: Dict[str, int] = {}


def _uid(prefix: str) -> str:
    _counter[prefix] = _counter.get(prefix, 0) + 1
    return f"{prefix}-{_counter[prefix]:03d}"


# ---------------------------------------------------------------------------
# Case builders
# ---------------------------------------------------------------------------


def _primitive_creation_case(primitive: str) -> Dict[str, Any]:
    name = _PRIM_NAME[primitive]
    return {
        "fixture_version": "3.0",
        "id": _uid("SYN-OBJ"),
        "category": "Object Creation",
        "difficulty": "Short",
        "task_family": "primitive_creation",
        "prompt_variants": [
            f"Add a {name} to the scene",
            f"Create a {name}",
            f"Please add a {name}",
            f"Insert a {name}",
        ],
        "initial_scene": {"mode": "OBJECT", "objects": []},
        "hard_constraints": {
            "mesh_object_count": {"minimum": 1},
            "required_object_types": ["MESH"],
        },
        "topology_policy": {"manifold_required": False, "quad_ratio_min": 0.0},
        "soft_constraints": [
            {"name": "single object", "metric": "total_mesh_objects",
             "direction": "exact", "target": 1.0, "tolerance": 0.0, "weight": 0.5},
        ],
        "style_intent": {"explicit": False, "concept": name, "acceptable_styles": ["geometric"]},
        "judge_policy": "skip",
        "artifact_policy": {"require_screenshot": True, "write_scene_stats": True},
    }


def _parameterized_case(primitive: str, size_label: str) -> Dict[str, Any]:
    name = _PRIM_NAME[primitive]
    sz = _SIZES[size_label]
    r = sz["radius"]
    return {
        "fixture_version": "3.0",
        "id": _uid("SYN-PAR"),
        "category": "Object Creation",
        "difficulty": "Medium",
        "task_family": "parameterized_primitive_creation",
        "prompt_variants": [
            f"Add a {size_label} {name} with radius {r}m",
            f"Create a {name} about {r * 2} meters wide",
            f"Make a {size_label} {name}",
        ],
        "initial_scene": {"mode": "OBJECT", "objects": []},
        "hard_constraints": {
            "mesh_object_count": {"minimum": 1},
            "bounding_boxes": [{
                "target": "__scene__",
                "size_range": {"minimum": sz["bbox_min"], "maximum": sz["bbox_max"]},
            }],
        },
        "topology_policy": {"manifold_required": False, "quad_ratio_min": 0.0},
        "soft_constraints": [],
        "style_intent": {"explicit": False, "concept": name, "acceptable_styles": ["geometric"]},
        "judge_policy": "skip",
        "artifact_policy": {"require_screenshot": True, "write_scene_stats": True},
    }


def _material_color_case(primitive: str, color_name: str) -> Dict[str, Any]:
    name = _PRIM_NAME[primitive]
    color = _COLORS[color_name]
    return {
        "fixture_version": "3.0",
        "id": _uid("SYN-MAT"),
        "category": "Materials & Shading",
        "difficulty": "Short",
        "task_family": "material_color_assignment",
        "prompt_variants": [
            f"Make the {name} {color_name}",
            f"Apply a {color_name} material to the {name}",
            f"Color the {name} {color_name}",
            f"Give the {name} a {color_name} color",
        ],
        "initial_scene": {
            "mode": "OBJECT",
            "objects": [{"primitive": primitive, "name": primitive.title()}],
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
# Generator
# ---------------------------------------------------------------------------


def generate(max_cases: int = 50) -> List[Dict[str, Any]]:
    """Generate cases: 5 primitive creation + 15 parameterized + 30 material = 50."""
    cases: List[Dict[str, Any]] = []

    # 5 primitive creation (one per primitive)
    for prim in _PRIMITIVES:
        cases.append(_primitive_creation_case(prim))

    # 15 parameterized (5 primitives × 3 sizes)
    for prim in _PRIMITIVES:
        for size in ["small", "medium", "large"]:
            cases.append(_parameterized_case(prim, size))

    # 30 material color (5 primitives × 6 colors)
    for prim in _PRIMITIVES:
        for color in _COLORS:
            cases.append(_material_color_case(prim, color))

    return cases[:max_cases]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic v3.0 test cases")
    parser.add_argument(
        "--out",
        default="fixtures/synthetic/generated_primitive_cases.json",
        help="Output JSON path",
    )
    parser.add_argument("--max", type=int, default=50, help="Max cases to emit")
    args = parser.parse_args()

    cases = generate(args.max)
    suite = {"suite_id": "synthetic-v3-primitives", "fixture_version": "3.0", "cases": cases}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(suite, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {len(cases)} cases → {out}")


if __name__ == "__main__":
    main()
