import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .contracts import compile_steps_to_legacy_ops, compile_steps_to_typed_commands
    from .executor import BenchmarkSafetyError, DualContractExecutor
    from .schema import TestCaseCard, TestSuite
except ImportError:  # pragma: no cover - Blender script fallback
    from contracts import compile_steps_to_legacy_ops, compile_steps_to_typed_commands
    from executor import BenchmarkSafetyError, DualContractExecutor
    from schema import TestCaseCard, TestSuite


SAFE_STEP_CATALOG = {
    "ADD_MESH": "Primitive creation with explicit dimensions",
    "SET_MODE": "Object/Edit mode transitions only",
    "TRANSLATE": "Object or edit-space translation",
    "SCALE": "Object or edit-space scaling",
    "ROTATE": "Axis-aligned rotation",
    "BEVEL": "Safe bevel edit operation",
    "INSET": "Safe inset edit operation",
    "EXTRUDE_REGION": "Safe extrude-region move",
    "SET_CAMERA": "Assign an existing camera",
    "SET_MATERIAL": "Assign or recolor a simple material",
}


SAFE_CASE_FAMILIES = [
    "primitive_creation",
    "primitive_transform",
    "edit_bevel",
    "edit_inset",
    "edit_extrude_region",
    "simple_assembly",
]


class SyntheticGroundTruthPipeline:
    def __init__(self, executor: DualContractExecutor, output_dir: Optional[str] = None):
        self.executor = executor
        self.output_dir = Path(output_dir) if output_dir else Path(__file__).resolve().parent / "fixtures" / "synthetic"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir = self.output_dir / "quarantine"
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

    def validate_case(self, case: TestCaseCard) -> Dict[str, Any]:
        legacy_ops, legacy_gaps = compile_steps_to_legacy_ops(case.expected_steps)
        typed_commands, typed_gaps = compile_steps_to_typed_commands(case.expected_steps)
        result = {
            "case_id": case.id,
            "accepted": False,
            "reference_signature": None,
            "legacy_coverage_gaps": legacy_gaps,
            "typed_coverage_gaps": typed_gaps,
            "legacy_ops": [op.model_dump(mode="json") for op in legacy_ops],
            "typed_commands": [cmd.model_dump(mode="json") for cmd in typed_commands],
            "errors": [],
        }

        try:
            reference = self.executor.build_reference(case)
            result["reference_signature"] = reference.geometry_signature
            result["accepted"] = True
        except (BenchmarkSafetyError, Exception) as exc:  # pragma: no cover - Blender-only path
            result["errors"].append(str(exc))
            result["accepted"] = False
        return result

    def validate_suite(self, suite: TestSuite) -> List[Dict[str, Any]]:
        return [self.validate_case(case) for case in suite.cases]

    def persist_case(self, case: TestCaseCard, *, filename: Optional[str] = None) -> Path:
        validation = self.validate_case(case)
        destination_dir = self.output_dir if validation["accepted"] else self.quarantine_dir
        target_name = filename or f"{case.id}.json"
        target_path = destination_dir / target_name
        with open(target_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "validation": validation,
                    "case": case.model_dump(mode="json", by_alias=True),
                },
                handle,
                indent=2,
            )
        return target_path

