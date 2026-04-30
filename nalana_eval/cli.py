"""CLI entry point: nalana-eval (and sub-tools).

Usage examples:
    python -m nalana_eval.cli --cases 5 --models mock --simple-mode
    python -m nalana_eval.cli --cases 5 --models mock --mock-blender
    python -m nalana_eval.cli history --model gpt-4o --last 5
    python -m nalana_eval.cli review --collect artifacts/.../report.md
    python -m nalana_eval.cli calibrate --judge-model gpt-4o
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        level=level,
        stream=sys.stderr,
    )


def _parse_dist(s: str) -> Dict[str, float]:
    """'short:0.4,medium:0.4,long:0.2' → {'short': 0.4, ...}"""
    result: Dict[str, float] = {}
    for part in (s or "").split(","):
        part = part.strip()
        if not part:
            continue
        k, _, v = part.partition(":")
        result[k.strip()] = float(v.strip())
    return result


def _parse_models(s: str) -> List[str]:
    return [m.strip() for m in (s or "").split(",") if m.strip()]


def _load_dotenv(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _load_case_ids_from_jsonl(path: str) -> Set[str]:
    """Read case_ids from a failures.jsonl written by harness."""
    ids: Set[str] = set()
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                data = json.loads(line)
                if "case_id" in data:
                    ids.add(data["case_id"])
    except Exception as exc:
        print(f"Warning: could not read cases from {path}: {exc}", file=sys.stderr)
    return ids


def _make_runner(model_id: str, system_prompt: str, config: "object") -> "object":
    """Instantiate the correct runner class based on model_id prefix."""
    kw = {
        "system_prompt": system_prompt,
        "temperature": getattr(config, "temperature", 0.7),
        "seed": getattr(config, "seed", 42),
    }
    if model_id == "mock":
        from nalana_eval.runners.mock_runner import MockRunner  # noqa: PLC0415
        return MockRunner(model_id="mock", **kw)
    if model_id.startswith("gpt") or model_id.startswith("o1") or model_id.startswith("o3"):
        from nalana_eval.runners.openai_runner import OpenAIRunner  # noqa: PLC0415
        return OpenAIRunner(model_id=model_id, **kw)
    if model_id.startswith("claude"):
        from nalana_eval.runners.anthropic_runner import AnthropicRunner  # noqa: PLC0415
        return AnthropicRunner(model_id=model_id, **kw)
    if model_id.startswith("gemini"):
        from nalana_eval.runners.gemini_runner import GeminiRunner  # noqa: PLC0415
        return GeminiRunner(model_id=model_id, **kw)
    # Fallback: try OpenAI-compatible
    from nalana_eval.runners.openai_runner import OpenAIRunner  # noqa: PLC0415
    return OpenAIRunner(model_id=model_id, **kw)


# ---------------------------------------------------------------------------
# Subcommand: benchmark
# ---------------------------------------------------------------------------


def cmd_benchmark(args: argparse.Namespace) -> None:
    from nalana_eval.harness import Harness  # noqa: PLC0415
    from nalana_eval.judge import Judge  # noqa: PLC0415
    from nalana_eval.schema import BenchmarkRunConfig, TestSuite  # noqa: PLC0415
    from nalana_eval.workers.pool import WorkerPool  # noqa: PLC0415
    from nalana_eval.workers.simple_runner import SimpleRunner  # noqa: PLC0415

    if args.api_keys_file:
        _load_dotenv(args.api_keys_file)

    # Load suite (--legacy-suite takes precedence over --suite)
    suite_path = args.legacy_suite or args.suite or "fixtures/starter_v3"
    suite = TestSuite.from_json_or_dir(suite_path)

    # Filter to specific cases from a failures.jsonl
    if getattr(args, "cases_from", "") and args.cases_from:
        case_ids = _load_case_ids_from_jsonl(args.cases_from)
        if case_ids:
            suite = TestSuite(
                suite_id=suite.suite_id,
                fixture_version=suite.fixture_version,
                cases=[c for c in suite.cases if c.id in case_ids],
            )
            print(f"Filtered suite to {len(suite.cases)} cases from {args.cases_from}", file=sys.stderr)

    model_ids = _parse_models(args.models)
    if not model_ids:
        print("Error: --models is required", file=sys.stderr)
        sys.exit(1)

    config = BenchmarkRunConfig(
        cases=args.cases,
        pass_at_k=args.pass_at_k,
        models=model_ids,
        judge_model=args.judge_model or "",
        system_prompt_version=args.system_prompt,
        temperature=args.temperature,
        seed=args.seed,
        workers=args.workers,
        simple_mode=args.simple_mode,
        suite_path=suite_path,
        output_dir=args.output_dir or "artifacts",
        judge_budget=args.judge_budget,
        difficulty_dist=_parse_dist(args.difficulty_dist),
        mock_blender=getattr(args, "mock_blender", False),
        retry_with_feedback=getattr(args, "retry_with_feedback", False),
    )

    system_prompt_path = Path("prompts") / f"{config.system_prompt_version}.md"
    system_prompt = system_prompt_path.read_text(encoding="utf-8") if system_prompt_path.exists() else ""

    runners = [_make_runner(mid, system_prompt, config) for mid in model_ids]

    judge = None
    if args.judge_model and not args.no_judge:
        judge = Judge(
            judge_model=args.judge_model,
            budget_remaining=args.judge_budget,
            db_path=Path("db/judge_cache.sqlite"),
        )

    worker_pool = None
    simple_runner = None
    if config.mock_blender or args.simple_mode:
        simple_runner = SimpleRunner(blender_bin=args.blender_bin or "blender")
    else:
        worker_pool = WorkerPool(
            n_workers=args.workers,
            blender_bin=args.blender_bin or "blender",
        )

    # Exclude non-serializable values (func, etc.) from cli_args
    cli_args = {k: v for k, v in vars(args).items() if not callable(v)}

    harness = Harness(
        suite=suite,
        runners=runners,
        config=config,
        output_base_dir=args.output_dir or "artifacts",
        judge=judge,
        worker_pool=worker_pool,
        simple_runner=simple_runner,
        cli_args=cli_args,
    )

    runs = harness.run()
    for run in runs:
        print(
            f"Run {run.run_id}: {run.model_id}  "
            f"hard_pass={run.metrics.hard_pass_rate:.1%}  "
            f"pass@k={run.metrics.pass_at_3:.1%}  "
            f"report={run.report_md_path}"
        )


# ---------------------------------------------------------------------------
# Subcommand: history
# ---------------------------------------------------------------------------


def cmd_history(args: argparse.Namespace) -> None:
    from nalana_eval import history  # noqa: PLC0415
    history.show(
        model_id=args.model,
        last_n=args.last,
        compare_models=_parse_models(args.compare or ""),
        case_id=args.case,
    )


# ---------------------------------------------------------------------------
# Subcommand: review
# ---------------------------------------------------------------------------


def cmd_review(args: argparse.Namespace) -> None:
    from nalana_eval import review  # noqa: PLC0415
    if args.collect:
        review.collect(args.collect)
    else:
        print("Error: --collect <report.md> required", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand: calibrate
# ---------------------------------------------------------------------------


def cmd_calibrate(args: argparse.Namespace) -> None:
    from calibration import calibrate  # noqa: PLC0415
    calibrate.run(
        judge_model=args.judge_model or "gpt-4o",
        reference_dir=args.reference_dir or "calibration/reference_images",
        output_dir=args.output_dir or "calibration/baseline_results",
    )


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _add_benchmark_parser(sub: argparse.Action) -> None:
    p = sub.add_parser("benchmark", help="Run benchmark (default subcommand)")
    p.add_argument("--cases", type=int, default=0, help="Number of cases (0=all)")
    p.add_argument("--models", required=True, help="Comma-separated model IDs")
    p.add_argument("--suite", default="", help="Path to suite JSON or directory")
    p.add_argument("--legacy-suite", default="", help="Path to v2 suite JSON (auto-converted)")
    p.add_argument("--cases-from", default="", metavar="FAILURES_JSONL",
                   help="Re-run only cases listed in a failures.jsonl")
    p.add_argument("--pass-at-k", type=int, default=3)
    p.add_argument("--judge-model", default="", help="Model ID for LLM-as-Judge")
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--judge-budget", type=float, default=10.0)
    p.add_argument("--system-prompt", default="eval-default")
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--simple-mode", action="store_true")
    p.add_argument("--mock-blender", action="store_true",
                   help="Skip real Blender; use stub snapshot + placeholder PNG (CI mode)")
    p.add_argument("--blender-bin", default="blender")
    p.add_argument("--output-dir", default="artifacts")
    p.add_argument("--difficulty-dist", default="", help="e.g. Short:0.4,Medium:0.4,Long:0.2")
    p.add_argument("--retry-with-feedback", action="store_true",
                   help="Enable retry-with-feedback loop. When a pass@k attempt "
                        "fails, the next attempt's prompt is augmented with a "
                        "structured summary of what went wrong (failure class, "
                        "executed steps, scene snapshot). Default OFF — see "
                        "ADR-004 for the data behind this default.")
    p.add_argument("--api-keys-file", default="")
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=cmd_benchmark)


def _add_history_parser(sub: argparse.Action) -> None:
    p = sub.add_parser("history", help="Query benchmark history")
    p.add_argument("--model", default="", help="Filter by model_id")
    p.add_argument("--last", type=int, default=10, help="Show last N runs")
    p.add_argument("--compare", default="", help="Comma-separated models to compare")
    p.add_argument("--case", default="", help="Filter by case_id")
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=cmd_history)


def _add_review_parser(sub: argparse.Action) -> None:
    p = sub.add_parser("review", help="Collect human review annotations from report.md")
    p.add_argument("--collect", metavar="REPORT_MD", help="Path to report.md to parse")
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=cmd_review)


def _add_calibrate_parser(sub: argparse.Action) -> None:
    p = sub.add_parser("calibrate", help="Run judge calibration against reference images")
    p.add_argument("--judge-model", default="gpt-4o")
    p.add_argument("--reference-dir", default="calibration/reference_images")
    p.add_argument("--output-dir", default="calibration/baseline_results")
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(func=cmd_calibrate)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="nalana-eval",
        description="Nalana Benchmark Evaluation System v3.0",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    sub = parser.add_subparsers(dest="command")
    _add_benchmark_parser(sub)
    _add_history_parser(sub)
    _add_review_parser(sub)
    _add_calibrate_parser(sub)

    # Allow running `nalana-eval --cases 5 --models mock` without "benchmark" subcommand
    # by injecting "benchmark" if first arg doesn't look like a known subcommand
    known_commands = {"benchmark", "history", "review", "calibrate"}
    argv = sys.argv[1:]
    if argv and argv[0] not in known_commands and not argv[0].startswith("-"):
        pass  # unknown positional — let argparse error naturally
    elif argv and argv[0] not in known_commands:
        argv = ["benchmark"] + argv

    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))

    if not hasattr(args, "func") or args.func is None:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
