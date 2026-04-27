"""Benchmark harness — main orchestrator.

Ties together: suite loading, model runners, Blender workers,
constraint evaluation, judge scoring, CSV persistence, and reporting.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import random
import subprocess
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from nalana_eval.evaluator import ConstraintEvaluator
from nalana_eval.judge import Judge
from nalana_eval.runners.base import BaseModelRunner
from nalana_eval.schema import (
    AttemptArtifact,
    BenchmarkRun,
    BenchmarkRunConfig,
    Category,
    Difficulty,
    FailureClass,
    RunMetrics,
    SceneSnapshot,
    TestCaseCard,
    TestSuite,
)
from nalana_eval.workers.pool import WorkerPool
from nalana_eval.workers.simple_runner import SimpleRunner

logger = logging.getLogger(__name__)

_HONEYPOT_INTERVAL = 10  # insert one honeypot every N cases


def _gen_id(n: int = 8) -> str:
    return uuid.uuid4().hex[:n]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _load_system_prompt(version: str) -> str:
    """Load system prompt from prompts/<version>.md."""
    prompt_dir = Path(__file__).parent.parent / "prompts"
    candidates = [
        prompt_dir / f"{version}.md",
        prompt_dir / "eval_default.md",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    logger.warning("System prompt %r not found; using empty prompt", version)
    return ""


def _select_prompt(case: TestCaseCard, attempt_index: int, rng: random.Random) -> str:
    """Pick a prompt variant. Cycle through variants across attempts."""
    if not case.prompt_variants:
        return ""
    idx = attempt_index % len(case.prompt_variants)
    return case.prompt_variants[idx]


def _sample_cases(
    suite: TestSuite,
    n_cases: int,
    difficulty_dist: Dict[str, float],
    rng: random.Random,
) -> List[TestCaseCard]:
    """Sample cases from the suite respecting difficulty distribution."""
    if n_cases <= 0 or n_cases >= len(suite.cases):
        return list(suite.cases)

    if not difficulty_dist:
        return rng.sample(suite.cases, min(n_cases, len(suite.cases)))

    # Group by difficulty
    by_difficulty: Dict[str, List[TestCaseCard]] = defaultdict(list)
    for c in suite.cases:
        by_difficulty[c.difficulty.value].append(c)

    result: List[TestCaseCard] = []
    total_weight = sum(difficulty_dist.values())
    for diff_name, weight in difficulty_dist.items():
        target_count = int(round(n_cases * weight / total_weight))
        pool = by_difficulty.get(diff_name, [])
        sampled = rng.sample(pool, min(target_count, len(pool)))
        result.extend(sampled)

    # Fill up to n_cases if rounding left gaps
    remaining = [c for c in suite.cases if c not in result]
    rng.shuffle(remaining)
    result.extend(remaining[:max(0, n_cases - len(result))])
    return result[:n_cases]


def _compute_metrics(
    attempts: List[AttemptArtifact],
    pass_at_k: int,
    run_start: float,
) -> RunMetrics:
    """Aggregate attempt-level data into run-level metrics."""
    if not attempts:
        return RunMetrics()

    # Group by case_id
    by_case: Dict[str, List[AttemptArtifact]] = defaultdict(list)
    for a in attempts:
        by_case[a.case_id].append(a)

    # pass@1 = fraction of cases where attempt 0 passed
    pass_at_1_count = sum(
        1 for attempts_list in by_case.values()
        if any(a.attempt_index == 0 and a.pass_overall for a in attempts_list)
    )
    # pass@k = fraction of cases where at least one attempt passed
    pass_at_k_count = sum(
        1 for attempts_list in by_case.values()
        if any(a.pass_overall for a in attempts_list)
    )

    n_cases = len(by_case)
    n_attempts = len(attempts)

    exec_success = sum(1 for a in attempts if a.execution_success)
    hard_pass = sum(1 for a in attempts if a.passed_hard_constraints)
    topo_pass = sum(1 for a in attempts if a.passed_topology)
    soft_total = sum(a.soft_score for a in attempts)

    judge_semantics = [a.judge_result.semantic for a in attempts if a.judge_result]
    judge_aesthetics = [a.judge_result.aesthetic for a in attempts if a.judge_result]
    judge_professionals = [a.judge_result.professional for a in attempts if a.judge_result]

    honeypots = [a for a in attempts if a.is_honeypot]
    honeypot_caught = sum(
        1 for a in honeypots
        if a.judge_result and a.judge_result.semantic <= 2.0
    )

    difficulty_dist: Dict[str, int] = Counter()
    category_dist: Dict[str, int] = Counter()
    failure_reasons: Dict[str, int] = Counter()
    for a in attempts:
        if not a.pass_overall:
            failure_reasons[a.failure_class.value] += 1

    return RunMetrics(
        total_cases=n_cases,
        total_attempts=n_attempts,
        execution_success_rate=exec_success / n_attempts if n_attempts else 0.0,
        hard_pass_rate=hard_pass / n_attempts if n_attempts else 0.0,
        topology_pass_rate=topo_pass / n_attempts if n_attempts else 0.0,
        avg_soft_score=soft_total / n_attempts if n_attempts else 0.0,
        pass_at_1=pass_at_1_count / n_cases if n_cases else 0.0,
        pass_at_3=pass_at_k_count / n_cases if n_cases else 0.0,
        avg_judge_semantic=sum(judge_semantics) / len(judge_semantics) if judge_semantics else None,
        avg_judge_aesthetic=sum(judge_aesthetics) / len(judge_aesthetics) if judge_aesthetics else None,
        avg_judge_professional=sum(judge_professionals) / len(judge_professionals) if judge_professionals else None,
        judge_reliable=all(
            a.judge_result and a.judge_result.semantic <= 2.0 for a in honeypots
        ) if honeypots else True,
        judge_honeypot_catch_rate=(
            honeypot_caught / len(honeypots) if honeypots else None
        ),
        avg_model_latency_ms=sum(a.model_latency_ms for a in attempts) / n_attempts if n_attempts else 0.0,
        avg_execution_latency_ms=sum(a.execution_latency_ms for a in attempts) / n_attempts if n_attempts else 0.0,
        total_cost_usd=sum(a.cost_usd for a in attempts),
        total_duration_s=time.perf_counter() - run_start,
        top_failure_reasons=dict(failure_reasons.most_common(10)),
    )


# ---------------------------------------------------------------------------
# Honeypot case builder
# ---------------------------------------------------------------------------


def _make_honeypot_case(base_id: str) -> TestCaseCard:
    """Build a known-bad case to test judge calibration."""
    from nalana_eval.schema import (  # noqa: PLC0415
        ArtifactPolicy, HardConstraints, InitialScene, StyleIntent, TopologyPolicy,
        TaskFamily,
    )
    return TestCaseCard(
        id=f"HONEYPOT_{base_id}",
        category=Category.OBJECT_CREATION,
        difficulty=Difficulty.SHORT,
        task_family=TaskFamily.PRIMITIVE_CREATION,
        prompt_variants=["Create a complex detailed 3D sculpture"],
        initial_scene=InitialScene(),
        hard_constraints=HardConstraints(),
        topology_policy=TopologyPolicy(),
        style_intent=StyleIntent(concept="sculpture"),
        artifact_policy=ArtifactPolicy(require_screenshot=True),
    )


# ---------------------------------------------------------------------------
# Core harness
# ---------------------------------------------------------------------------


class Harness:
    """Main benchmark orchestrator."""

    def __init__(
        self,
        suite: TestSuite,
        runners: List[BaseModelRunner],
        config: BenchmarkRunConfig,
        output_base_dir: Optional[str] = None,
        judge: Optional[Judge] = None,
        worker_pool: Optional[WorkerPool] = None,
        simple_runner: Optional[SimpleRunner] = None,
    ) -> None:
        self.suite = suite
        self.runners = runners
        self.config = config
        self.output_base_dir = Path(output_base_dir or "artifacts")
        self.judge = judge
        self.worker_pool = worker_pool
        self.simple_runner = simple_runner
        self._evaluator = ConstraintEvaluator()
        self._rng = random.Random(config.seed)
        self._run_group_id = _gen_id(8)

    def _blender_submit(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        if self.config.simple_mode:
            if self.simple_runner is None:
                self.simple_runner = SimpleRunner()
            return self.simple_runner.run(msg)
        if self.worker_pool is None:
            self.worker_pool = WorkerPool(n_workers=self.config.workers)
        return self.worker_pool.submit(msg)

    def _run_single_attempt(
        self,
        runner: BaseModelRunner,
        case: TestCaseCard,
        attempt_index: int,
        output_dir: Path,
        is_honeypot: bool = False,
    ) -> AttemptArtifact:
        prompt_used = _select_prompt(case, attempt_index, self._rng)

        # Step 1: call model
        invocation = runner.generate(prompt_used, case, attempt_index)

        artifact = AttemptArtifact(
            case_id=case.id,
            attempt_index=attempt_index,
            model_id=runner.model_id,
            prompt_used=prompt_used,
            raw_output=invocation.raw_output,
            normalized_output=invocation.normalized_output,
            parse_success=invocation.parse_success,
            safety_success=invocation.safety_success,
            model_latency_ms=invocation.model_latency_ms,
            cost_usd=invocation.cost_usd,
            is_honeypot=is_honeypot,
        )

        if not invocation.parse_success:
            artifact.failure_class = FailureClass.PARSE_ERROR
            artifact.failure_reason = invocation.parse_error or "Parse failed"
            return artifact

        if not invocation.safety_success:
            artifact.failure_class = FailureClass.SAFETY_BLOCKED
            artifact.failure_reason = invocation.parse_error or "Safety blocked"
            return artifact

        # Step 2: execute in Blender
        normalized_dicts = [
            {"kind": s.kind.value, "args": s.args}
            for s in invocation.normalized_output
        ]
        blender_msg: Dict[str, Any] = {
            "case": case.model_dump(mode="json"),
            "normalized_steps": normalized_dicts,
            "attempt_index": attempt_index,
            "output_dir": str(output_dir),
        }

        try:
            result = self._blender_submit(blender_msg)
        except Exception as exc:
            logger.error("Blender submit failed for %s/%d: %s", case.id, attempt_index, exc)
            artifact.failure_class = FailureClass.EXECUTION_ERROR
            artifact.failure_reason = str(exc)
            return artifact

        execution_success = bool(result.get("ok", False))
        artifact.execution_success = execution_success
        artifact.execution_latency_ms = float(result.get("execution_latency_ms", 0.0))
        artifact.screenshot_path = result.get("screenshot_path", "")
        artifact.scene_stats_path = result.get("scene_stats_path", "")

        # Step 3: parse snapshot + evaluate constraints
        snapshot_dict = result.get("snapshot") or {}
        try:
            snap = SceneSnapshot.model_validate(snapshot_dict)
        except Exception as exc:
            logger.warning("SceneSnapshot parse failed for %s: %s", case.id, exc)
            snap = SceneSnapshot()
        artifact.scene_snapshot = snap

        eval_result = self._evaluator.evaluate(case, snap, execution_success)
        artifact.passed_hard_constraints = eval_result.hard_pass
        artifact.passed_topology = eval_result.topology_pass
        artifact.soft_score = eval_result.soft_score
        artifact.failure_class = eval_result.failure_class
        artifact.failure_reason = eval_result.failure_reason
        artifact.pass_overall = eval_result.hard_pass and eval_result.topology_pass

        # Step 4: judge (if policy allows and screenshot available)
        if self.judge and not is_honeypot:
            try:
                judge_result = self.judge.judge(case, prompt_used, artifact.screenshot_path)
                artifact.judge_result = judge_result
            except Exception as exc:
                logger.warning("Judge failed for %s: %s", case.id, exc)

        return artifact

    def _run_single_model(
        self,
        runner: BaseModelRunner,
        cases: List[TestCaseCard],
    ) -> BenchmarkRun:
        run_id = _gen_id(8)
        timestamp = _utc_now()
        output_dir = self.output_base_dir / f"run_{timestamp[:10].replace('-', '')}_{run_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        system_prompt = _load_system_prompt(self.config.system_prompt_version)
        runner.system_prompt = system_prompt

        logger.info(
            "Starting run %s for model %s — %d cases × %d attempts",
            run_id, runner.model_id, len(cases), self.config.pass_at_k,
        )

        run_start = time.perf_counter()
        all_attempts: List[AttemptArtifact] = []
        honeypot_counter = 0

        for case_idx, case in enumerate(cases):
            # Insert honeypot case periodically
            if case_idx > 0 and case_idx % _HONEYPOT_INTERVAL == 0:
                honeypot = _make_honeypot_case(f"{run_id}_{honeypot_counter}")
                honeypot_counter += 1
                hp_attempt = self._run_single_attempt(
                    runner, honeypot, 0, output_dir, is_honeypot=True
                )
                all_attempts.append(hp_attempt)

            for attempt_idx in range(self.config.pass_at_k):
                attempt = self._run_single_attempt(runner, case, attempt_idx, output_dir)
                all_attempts.append(attempt)

                if attempt.pass_overall:
                    # pass@k satisfied — no need for more attempts
                    break

        metrics = _compute_metrics(all_attempts, self.config.pass_at_k, run_start)

        run = BenchmarkRun(
            run_id=run_id,
            run_group_id=self._run_group_id,
            timestamp_utc=timestamp,
            model_id=runner.model_id,
            suite_id=self.suite.suite_id,
            config=self.config,
            attempts=all_attempts,
            metrics=metrics,
            git_commit=_git_commit(),
        )
        return run

    def run(self) -> List[BenchmarkRun]:
        """Run benchmark for all configured models. Returns list of BenchmarkRun objects."""
        from nalana_eval import csv_db, reporting  # noqa: PLC0415

        cases = _sample_cases(
            self.suite,
            self.config.cases,
            self.config.difficulty_dist,
            self._rng,
        )
        logger.info("Sampled %d cases from suite %r", len(cases), self.suite.suite_id)

        output_dir = self.output_base_dir / f"run_group_{self._run_group_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        all_runs: List[BenchmarkRun] = []

        use_pool = not self.config.simple_mode and self.config.workers > 1 and self.worker_pool is not None
        if use_pool:
            self.worker_pool.start()  # type: ignore[union-attr]

        try:
            for runner in self.runners:
                try:
                    brun = self._run_single_model(runner, cases)
                    all_runs.append(brun)

                    # Persist immediately after each model completes
                    for attempt in brun.attempts:
                        case_map = {c.id: c for c in cases}
                        case = case_map.get(attempt.case_id)
                        if case:
                            csv_db.append_attempt(brun.run_id, attempt, case)

                    csv_db.append_run(brun, judge_model=self.config.judge_model)
                except Exception as exc:
                    logger.error("Run failed for model %s: %s", runner.model_id, exc)
        finally:
            if use_pool and self.worker_pool:
                self.worker_pool.shutdown()

        # Generate report
        try:
            reporting.generate(all_runs, output_dir, run_group_id=self._run_group_id)
        except Exception as exc:
            logger.error("Reporting failed: %s", exc)

        return all_runs
