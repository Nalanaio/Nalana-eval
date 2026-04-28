import json
import os
import sys

import bpy  # pyright: ignore[reportMissingImports]

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from model_runners import GeminiRunner, StaticPayloadRunner
from schema import OutputContract, TestSuite
from test_harness import NalanaTestHarness


def run_sandbox_test():
    print("\n--- Activating Nalana Benchmark Smoke Test ---")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    fixture_path = os.path.join(current_dir, "fixtures", "sample_cases_v2.json")

    suite = TestSuite.from_json(fixture_path)
    baseline_payloads = {}
    candidate_payloads = {}

    for case in suite.cases:
        baseline_payloads[case.id] = json.dumps(
            [op.model_dump(mode="json") for op in case.compiled_payloads.legacy_ops]
        )
        candidate_payloads[case.id] = json.dumps(
            [cmd.model_dump(mode="json") for cmd in case.compiled_payloads.typed_commands]
        )

    harness = NalanaTestHarness(fixture_path)
    baseline_runner = GeminiRunner(baseline_payloads, output_contract=OutputContract.LEGACY_OPS)
    candidate_runner = StaticPayloadRunner(
        candidate_payloads,
        model_id="candidate-typed-smoke",
        output_contract=OutputContract.TYPED_COMMANDS,
    )

    baseline_run = harness.run_suite(baseline_runner)
    candidate_run = harness.run_suite(candidate_runner)

    print(f"✅ Baseline report: {baseline_run.report_markdown_path}")
    print(f"✅ Candidate report: {candidate_run.report_markdown_path}")

    if bpy.data.objects:
        print(f"📍 Active scene objects after smoke test: {len(bpy.data.objects)}")
    print("\n--- Benchmark Smoke Test Completed ---")


if __name__ == "__main__":
    run_sandbox_test()
