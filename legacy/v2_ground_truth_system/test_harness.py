import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

try:
    from .executor import BenchmarkSafetyError, DualContractExecutor
    from .metrics_evaluator import MetricsEvaluator
    from .model_runners import ModelRunner, XmlRpcModelRunner
    from .reporting import BenchmarkReporter
    from .schema import (
        AttemptArtifact,
        BenchmarkRun,
        CaseResult,
        FailureClass,
        OutputContract,
        PROMPT_TEMPLATE_VERSION,
        TestSuite,
    )
except ImportError:  # pragma: no cover - Blender script fallback
    from executor import BenchmarkSafetyError, DualContractExecutor
    from metrics_evaluator import MetricsEvaluator
    from model_runners import ModelRunner, XmlRpcModelRunner
    from reporting import BenchmarkReporter
    from schema import AttemptArtifact, BenchmarkRun, CaseResult, FailureClass, OutputContract, PROMPT_TEMPLATE_VERSION, TestSuite


class NalanaTestHarness:
    def __init__(
        self,
        suite_path: str,
        *,
        repo_root: Optional[str] = None,
        reporter: Optional[BenchmarkReporter] = None,
        executor: Optional[DualContractExecutor] = None,
    ):
        self.suite_path = suite_path
        self.suite = TestSuite.from_json(suite_path)
        self.executor = executor or DualContractExecutor(repo_root=repo_root)
        self.evaluator = MetricsEvaluator()
        self.reporter = reporter or BenchmarkReporter(str(Path(__file__).resolve().parent))
        self.artifact_dir = Path(__file__).resolve().parent / "artifacts"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.failure_log_path = self.artifact_dir / "benchmark_failures.jsonl"

    def run_suite(self, runner: ModelRunner) -> BenchmarkRun:
        case_results: List[CaseResult] = []

        for case in self.suite.cases:
            try:
                reference_snapshot = self.executor.build_reference(case)
                reference_error = None
            except Exception as exc:
                reference_snapshot = None
                reference_error = str(exc)

            attempts: List[AttemptArtifact] = []
            for attempt_index, voice_command in enumerate(case.voice_commands):
                attempt = self._evaluate_attempt(
                    runner=runner,
                    case=case,
                    attempt_index=attempt_index,
                    voice_command=voice_command,
                    reference_snapshot=reference_snapshot,
                    reference_error=reference_error,
                )
                attempts.append(attempt)
                if not attempt.passed:
                    self._log_failure(case.id, attempt)

            case_result = self._build_case_result(case, attempts, reference_snapshot)
            case_results.append(case_result)

        run = BenchmarkRun(
            suite_id=self.suite.suite_id,
            fixture_version=self.suite.fixture_version,
            prompt_template_version=self.suite.prompt_template_version or PROMPT_TEMPLATE_VERSION,
            model_id=runner.model_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            case_results=case_results,
        )
        run.summary = self.reporter.summarize(case_results)
        run = self.reporter.attach_baseline(run)
        run = self.reporter.write_run(run)
        return run

    def run_models(self, runners: List[ModelRunner]) -> List[BenchmarkRun]:
        return [self.run_suite(runner) for runner in runners]

    def _evaluate_attempt(
        self,
        *,
        runner: ModelRunner,
        case,
        attempt_index: int,
        voice_command: str,
        reference_snapshot,
        reference_error: Optional[str],
    ) -> AttemptArtifact:
        invocation = runner.invoke(case, voice_command, attempt_index)
        artifact = AttemptArtifact(
            case_id=case.id,
            attempt_index=attempt_index,
            voice_command=voice_command,
            prompt=invocation.prompt,
            model_id=runner.model_id,
            detected_contract=invocation.detected_contract,
            raw_output=invocation.raw_output,
            normalized_output=invocation.normalized_output,
            parse_success=invocation.parse_error is None,
            model_latency_ms=invocation.model_latency_ms,
            total_latency_ms=invocation.model_latency_ms,
            error_message=invocation.parse_error,
        )

        if reference_error:
            artifact.failure_class = FailureClass.REFERENCE_ERROR
            artifact.error_message = reference_error
            return artifact

        artifact.command_accuracy = self.evaluator.calculate_command_accuracy(
            case.expected_steps,
            invocation.normalized_output,
        )
        artifact.parameter_accuracy = self.evaluator.calculate_parameter_accuracy(
            case.expected_steps,
            invocation.normalized_output,
        )
        artifact.sequence_accuracy = self.evaluator.calculate_sequence_accuracy(
            case.expected_steps,
            invocation.normalized_output,
        )

        if invocation.parse_error is not None:
            artifact.failure_class = FailureClass.PARSE_ERROR
            return artifact

        self.executor.reset_scene(case.initial_scene)
        try:
            outcome = self.executor.execute_attempt_steps(
                invocation.normalized_output,
                invocation.detected_contract,
            )
        except BenchmarkSafetyError as exc:
            artifact.failure_class = self._classify_runtime_error(str(exc))
            artifact.error_message = str(exc)
            return artifact
        except Exception as exc:
            artifact.failure_class = FailureClass.EXECUTION_ERROR
            artifact.error_message = str(exc)
            return artifact

        artifact.compiled_legacy_ops = outcome.get("compiled_legacy_ops", [])
        artifact.compiled_typed_commands = outcome.get("compiled_typed_commands", [])
        artifact.coverage_gaps = outcome.get("coverage_gaps", [])
        artifact.execution_latency_ms = outcome.get("execution_latency_ms", 0.0)
        artifact.total_latency_ms = artifact.model_latency_ms + artifact.execution_latency_ms

        if not outcome.get("success"):
            artifact.failure_class = outcome.get("failure_class", FailureClass.EXECUTION_ERROR)
            artifact.error_message = outcome.get("error_message")
            return artifact

        artifact.safety_success = True
        artifact.execution_success = True

        candidate_snapshot = outcome["snapshot"]
        artifact.reference_signature = reference_snapshot.geometry_signature if reference_snapshot else None
        artifact.candidate_signature = candidate_snapshot.geometry_signature
        artifact.topology_score = self.evaluator.calculate_topology_score(candidate_snapshot)
        artifact.chamfer_distance, artifact.sampling_mode = self.evaluator.calculate_chamfer_distance(
            reference_snapshot,
            candidate_snapshot,
        )
        artifact.geometry_success = (
            artifact.topology_score.quad_ratio >= case.quality_signals.quad_ratio_min
            and artifact.topology_score.manifold == case.quality_signals.manifold
            and artifact.chamfer_distance <= case.quality_signals.chamfer_threshold
        )
        artifact.passed = artifact.execution_success and artifact.geometry_success
        if not artifact.passed:
            artifact.failure_class = FailureClass.GEOMETRY_MISMATCH

        safe_model = runner.model_id.replace("/", "-").replace(" ", "-")
        render_path = str(self.artifact_dir / "renders" / safe_model / f"{case.id}_attempt{attempt_index}.png")
        try:
            self.executor.render_png(render_path)
            artifact.render_path = render_path
        except Exception:
            pass

        return artifact

    def _build_case_result(self, case, attempts: List[AttemptArtifact], reference_snapshot) -> CaseResult:
        pass_results = [attempt.passed for attempt in attempts]
        failure_summary = Counter(
            attempt.failure_class.value
            for attempt in attempts
            if attempt.failure_class != FailureClass.NONE
        )
        best_attempt_index = None
        for index, attempt in enumerate(attempts):
            if attempt.passed:
                best_attempt_index = index
                break

        return CaseResult(
            case_id=case.id,
            category=case.category,
            difficulty=case.difficulty,
            reference_signature=reference_snapshot.geometry_signature if reference_snapshot else None,
            typed_coverage=case.has_full_typed_coverage,
            attempts=attempts,
            pass_at_1=1.0 if attempts and attempts[0].passed else 0.0,
            pass_at_k=self.evaluator.calculate_pass_at_k(pass_results, k=min(3, len(pass_results))),
            best_attempt_index=best_attempt_index,
            failure_summary=dict(failure_summary),
        )

    def _log_failure(self, case_id: str, attempt: AttemptArtifact) -> None:
        payload = {
            "case_id": case_id,
            "attempt_index": attempt.attempt_index,
            "voice_command": attempt.voice_command,
            "failure_class": attempt.failure_class.value,
            "error_message": attempt.error_message,
            "detected_contract": attempt.detected_contract.value,
            "normalized_output": [step.model_dump(mode="json") for step in attempt.normalized_output],
        }
        with open(self.failure_log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

    @staticmethod
    def _classify_runtime_error(message: str) -> FailureClass:
        lowered = message.lower()
        if "coverage" in lowered:
            return FailureClass.COVERAGE_GAP
        if any(token in lowered for token in ("allowlisted", "quota", "timeout", "blocked", "safety")):
            return FailureClass.SAFETY_BLOCKED
        return FailureClass.EXECUTION_ERROR


def _build_runner_from_args(args: argparse.Namespace) -> ModelRunner:
    return XmlRpcModelRunner(
        args.rpc_url,
        method_name=args.rpc_method,
        payload_style=args.rpc_payload_style,
        model_id=args.model_id,
        output_contract=OutputContract(args.output_contract),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Nalana benchmark suite")
    parser.add_argument("suite_path", nargs="?", default="fixtures/sample_cases_v2.json")
    parser.add_argument("--rpc-url", default="http://127.0.0.1:8785/RPC2")
    parser.add_argument("--rpc-method", default="generate_json_payload")
    parser.add_argument("--rpc-payload-style", choices=["prompt_only", "structured"], default="prompt_only")
    parser.add_argument("--model-id", default="xmlrpc-model")
    parser.add_argument(
        "--output-contract",
        choices=[contract.value for contract in OutputContract],
        default=OutputContract.LEGACY_OPS.value,
    )
    args = parser.parse_args()

    harness = NalanaTestHarness(args.suite_path)
    runner = _build_runner_from_args(args)
    run = harness.run_suite(runner)
    print(f"Report written to {run.report_markdown_path}")


if __name__ == "__main__":
    main()

