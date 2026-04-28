import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    from .schema import BenchmarkRun, CaseResult, RunSummary
except ImportError:  # pragma: no cover - Blender script fallback
    from schema import BenchmarkRun, CaseResult, RunSummary


SUMMARY_KEYS = [
    "execution_success_rate",
    "geometry_success_rate",
    "pass_at_1",
    "pass_at_k",
    "avg_command_accuracy",
    "avg_parameter_accuracy",
    "avg_sequence_accuracy",
    "avg_latency_ms",
    "avg_chamfer_distance",
]


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    chars = [char if char.isalnum() else "-" for char in lowered]
    slug = "".join(chars)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "run"


class BaselineStore:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def key_for_run(self, run: BenchmarkRun) -> str:
        return "__".join(
            [
                slugify(run.suite_id),
                slugify(run.fixture_version),
                slugify(run.prompt_template_version),
                "google-gemini-3-pro",
            ]
        )

    def baseline_path(self, run: BenchmarkRun) -> Path:
        return self.base_dir / f"{self.key_for_run(run)}.json"

    def load(self, run: BenchmarkRun) -> Optional[BenchmarkRun]:
        path = self.baseline_path(run)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return BenchmarkRun.model_validate(json.load(handle))

    def ensure(self, run: BenchmarkRun, *, allow_create: bool) -> Tuple[Optional[BenchmarkRun], bool]:
        existing = self.load(run)
        if existing is not None:
            return existing, False
        if not allow_create:
            return None, False
        path = self.baseline_path(run)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(run.model_dump(mode="json"), handle, indent=2)
        return run, True


class BenchmarkReporter:
    def __init__(self, base_dir: Optional[str] = None):
        root = Path(base_dir) if base_dir else Path(__file__).resolve().parent
        self.results_dir = root / "results"
        self.baseline_store = BaselineStore(str(root / "baselines"))
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def summarize(self, case_results: List[CaseResult]) -> RunSummary:
        attempts = [attempt for case in case_results for attempt in case.attempts]
        summary = RunSummary(
            total_cases=len(case_results),
            total_attempts=len(attempts),
        )
        if not attempts:
            return summary

        summary.execution_success_rate = self._ratio(
            sum(1 for attempt in attempts if attempt.execution_success),
            len(attempts),
        )
        summary.geometry_success_rate = self._ratio(
            sum(1 for attempt in attempts if attempt.geometry_success),
            len(attempts),
        )
        summary.pass_at_1 = self._average(case.pass_at_1 for case in case_results)
        summary.pass_at_k = self._average(case.pass_at_k for case in case_results)
        summary.avg_command_accuracy = self._average(attempt.command_accuracy for attempt in attempts)
        summary.avg_parameter_accuracy = self._average(attempt.parameter_accuracy for attempt in attempts)
        summary.avg_sequence_accuracy = self._average(attempt.sequence_accuracy for attempt in attempts)
        summary.avg_latency_ms = self._average(attempt.total_latency_ms for attempt in attempts)

        chamfer_values = [attempt.chamfer_distance for attempt in attempts if attempt.chamfer_distance is not None]
        if chamfer_values:
            summary.avg_chamfer_distance = self._average(chamfer_values)

        summary.category_breakdown = self._group_breakdown(case_results, key_fn=lambda case: case.category.value)
        summary.difficulty_breakdown = self._group_breakdown(case_results, key_fn=lambda case: case.difficulty.value)

        failure_counts = Counter(
            attempt.failure_class.value
            for attempt in attempts
            if attempt.failure_class.value != "NONE"
        )
        summary.top_failure_reasons = dict(failure_counts.most_common(5))
        return summary

    def attach_baseline(self, run: BenchmarkRun) -> BenchmarkRun:
        allow_create = run.model_id == "google-gemini-3-pro"
        baseline, created = self.baseline_store.ensure(run, allow_create=allow_create)
        if baseline is None:
            return run

        run.baseline_reference = str(self.baseline_store.baseline_path(run))
        run.baseline_created = created
        deltas: Dict[str, Optional[float]] = {}
        for key in SUMMARY_KEYS:
            current = getattr(run.summary, key)
            baseline_value = getattr(baseline.summary, key)
            if current is None or baseline_value is None:
                deltas[key] = None
            else:
                deltas[key] = float(current) - float(baseline_value)
        run.baseline_deltas = deltas
        return run

    def write_run(self, run: BenchmarkRun) -> BenchmarkRun:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = self.results_dir / f"{timestamp}-{slugify(run.model_id)}"
        run_dir.mkdir(parents=True, exist_ok=True)

        markdown_path = run_dir / "report.md"
        json_path = run_dir / "report.json"
        csv_path = run_dir / "attempts.csv"
        run.report_markdown_path = str(markdown_path)
        run.report_json_path = str(json_path)
        markdown = self.render_markdown(run)

        with open(markdown_path, "w", encoding="utf-8") as handle:
            handle.write(markdown)
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(run.model_dump(mode="json"), handle, indent=2)
        self._write_attempt_csv(run, csv_path)
        return run

    _CSV_FIELDS = [
        "case_id", "prompt", "model", "attempt_index",
        "passed", "execution_success", "geometry_success",
        "topo_manifold", "topo_loose_geometry", "topo_face_quality",
        "topo_flipped_faces", "topo_overlapping_verts", "topo_duplicate_faces",
        "chamfer_distance", "command_accuracy", "parameter_accuracy", "sequence_accuracy",
        "failure_class", "render_path",
    ]

    def _write_attempt_csv(self, run: BenchmarkRun, path: Path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self._CSV_FIELDS)
            writer.writeheader()
            for case in run.case_results:
                for attempt in case.attempts:
                    topo = attempt.topology_score
                    writer.writerow({
                        "case_id": attempt.case_id,
                        "prompt": attempt.voice_command,
                        "model": attempt.model_id,
                        "attempt_index": attempt.attempt_index,
                        "passed": attempt.passed,
                        "execution_success": attempt.execution_success,
                        "geometry_success": attempt.geometry_success,
                        "topo_manifold": topo.manifold if topo else "",
                        "topo_loose_geometry": topo.loose_geometry_count if topo else "",
                        "topo_face_quality": round(topo.face_quality_score, 4) if topo else "",
                        "topo_flipped_faces": topo.flipped_face_count if topo else "",
                        "topo_overlapping_verts": topo.overlapping_verts if topo else "",
                        "topo_duplicate_faces": topo.duplicate_faces if topo else "",
                        "chamfer_distance": round(attempt.chamfer_distance, 6) if attempt.chamfer_distance is not None else "",
                        "command_accuracy": round(attempt.command_accuracy, 4),
                        "parameter_accuracy": round(attempt.parameter_accuracy, 4),
                        "sequence_accuracy": round(attempt.sequence_accuracy, 4),
                        "failure_class": attempt.failure_class.value,
                        "render_path": attempt.render_path or "",
                    })

    def render_markdown(self, run: BenchmarkRun) -> str:
        lines = [
            f"# Nalana Benchmark Report: {run.model_id}",
            "",
            "## Run Metadata",
            f"- Generated at: {run.generated_at}",
            f"- Suite: `{run.suite_id}`",
            f"- Fixture version: `{run.fixture_version}`",
            f"- Prompt template version: `{run.prompt_template_version}`",
        ]
        if run.baseline_reference:
            lines.append(f"- Baseline: `{run.baseline_reference}`")
            if run.baseline_created:
                lines.append("- Baseline status: created during this run")

        lines.extend(
            [
                "",
                "## Summary",
                f"- Cases: {run.summary.total_cases}",
                f"- Attempts: {run.summary.total_attempts}",
                f"- Execution success: {self._format_percent(run.summary.execution_success_rate)}",
                f"- Geometry success: {self._format_percent(run.summary.geometry_success_rate)}",
                f"- Pass@1: {self._format_percent(run.summary.pass_at_1)}",
                f"- Pass@k: {self._format_percent(run.summary.pass_at_k)}",
                f"- Avg command accuracy: {self._format_percent(run.summary.avg_command_accuracy)}",
                f"- Avg parameter accuracy: {self._format_percent(run.summary.avg_parameter_accuracy)}",
                f"- Avg sequence accuracy: {self._format_percent(run.summary.avg_sequence_accuracy)}",
                f"- Avg latency: {run.summary.avg_latency_ms:.2f} ms",
            ]
        )
        if run.summary.avg_chamfer_distance is not None:
            lines.append(f"- Avg Chamfer distance: {run.summary.avg_chamfer_distance:.6f}")

        if run.baseline_deltas:
            lines.extend(["", "## Baseline Delta vs Gemini 3 Pro"])
            for key in SUMMARY_KEYS:
                if key not in run.baseline_deltas:
                    continue
                delta = run.baseline_deltas[key]
                if delta is None:
                    lines.append(f"- {key}: n/a")
                elif key.endswith("_ms") or "chamfer" in key:
                    lines.append(f"- {key}: {delta:+.6f}")
                else:
                    lines.append(f"- {key}: {delta:+.2%}")

        lines.extend(["", "## Category Breakdown"])
        lines.extend(self._render_breakdown(run.summary.category_breakdown))
        lines.extend(["", "## Difficulty Breakdown"])
        lines.extend(self._render_breakdown(run.summary.difficulty_breakdown))

        lines.extend(["", "## Top Failure Reasons"])
        if run.summary.top_failure_reasons:
            for failure, count in run.summary.top_failure_reasons.items():
                lines.append(f"- {failure}: {count}")
        else:
            lines.append("- None")

        lines.extend(["", "## Case Appendix"])
        for case in run.case_results:
            lines.extend(
                [
                    f"### {case.case_id}",
                    f"- Category: {case.category.value}",
                    f"- Difficulty: {case.difficulty.value}",
                    f"- Typed coverage: {'yes' if case.typed_coverage else 'partial'}",
                    f"- Pass@1: {self._format_percent(case.pass_at_1)}",
                    f"- Pass@k: {self._format_percent(case.pass_at_k)}",
                ]
            )
            if case.failure_summary:
                lines.append(f"- Failure summary: {json.dumps(case.failure_summary, sort_keys=True)}")
            for attempt in case.attempts:
                lines.extend(
                    [
                        f"- Attempt {attempt.attempt_index + 1}: `{attempt.voice_command}`",
                        f"  Raw output: `{self._compact_json(attempt.raw_output)}`",
                        f"  Normalized: `{self._compact_json([step.model_dump(mode='json') for step in attempt.normalized_output])}`",
                        "  Metrics: "
                        f"execution={attempt.execution_success}, geometry={attempt.geometry_success}, "
                        f"command={attempt.command_accuracy:.2f}, parameter={attempt.parameter_accuracy:.2f}, "
                        f"sequence={attempt.sequence_accuracy:.2f}, latency_ms={attempt.total_latency_ms:.2f}, "
                        f"chamfer={attempt.chamfer_distance if attempt.chamfer_distance is not None else 'n/a'}",
                    ]
                )
                if attempt.failure_class.value != "NONE":
                    lines.append(f"  Failure: {attempt.failure_class.value} ({attempt.error_message})")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _compact_json(value: object) -> str:
        try:
            return json.dumps(value, separators=(",", ":"), sort_keys=True)[:400]
        except TypeError:
            return str(value)[:400]

    @staticmethod
    def _average(values: Iterable[float]) -> float:
        values = list(values)
        if not values:
            return 0.0
        return float(sum(values)) / len(values)

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        if denominator == 0:
            return 0.0
        return numerator / denominator

    @staticmethod
    def _format_percent(value: float) -> str:
        return f"{value:.2%}"

    def _group_breakdown(self, case_results: List[CaseResult], *, key_fn) -> Dict[str, Dict[str, float]]:
        grouped: Dict[str, List[CaseResult]] = defaultdict(list)
        for case in case_results:
            grouped[key_fn(case)].append(case)

        breakdown: Dict[str, Dict[str, float]] = {}
        for label, cases in grouped.items():
            attempts = [attempt for case in cases for attempt in case.attempts]
            breakdown[label] = {
                "cases": len(cases),
                "pass_at_1": self._average(case.pass_at_1 for case in cases),
                "pass_at_k": self._average(case.pass_at_k for case in cases),
                "execution_success_rate": self._ratio(
                    sum(1 for attempt in attempts if attempt.execution_success),
                    len(attempts) or 1,
                ),
                "avg_latency_ms": self._average(attempt.total_latency_ms for attempt in attempts) if attempts else 0.0,
            }
        return breakdown

    @staticmethod
    def _render_breakdown(breakdown: Dict[str, Dict[str, float]]) -> List[str]:
        if not breakdown:
            return ["- None"]
        lines: List[str] = []
        for label, values in sorted(breakdown.items()):
            lines.append(
                "- "
                f"{label}: cases={int(values['cases'])}, "
                f"pass@1={values['pass_at_1']:.2%}, "
                f"pass@k={values['pass_at_k']:.2%}, "
                f"execution={values['execution_success_rate']:.2%}, "
                f"avg_latency_ms={values['avg_latency_ms']:.2f}"
            )
        return lines
