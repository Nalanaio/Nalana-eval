#!/usr/bin/env python3
"""Interactive benchmark launcher.

Usage:
    python bench.py
"""
import getpass
import os
import subprocess
import sys
from pathlib import Path

# ── provider catalogue ────────────────────────────────────────────────────────

PROVIDERS = [
    ("mock",      "Mock         — no API key, instant"),
    ("anthropic", "Anthropic    — ANTHROPIC_API_KEY"),
    ("openai",    "OpenAI       — OPENAI_API_KEY"),
    ("gemini",    "Gemini       — GEMINI_API_KEY"),
]

PROVIDER_MODELS: dict[str, list[tuple[str, str]]] = {
    "anthropic": [
        ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
        ("claude-opus-4-7",   "Claude Opus 4.7"),
        ("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
    ],
    "openai": [
        ("gpt-5.5",    "GPT-5.5"),
        ("gpt-5.4",    "GPT-5.4"),
        ("gpt-4o",     "GPT-4o"),
        ("gpt-4o-mini","GPT-4o Mini"),
        ("o3",         "o3"),
        ("o1",         "o1"),
    ],
    "gemini": [
        ("gemini-2.5-pro",   "Gemini 2.5 Pro"),
        ("gemini-2.0-flash", "Gemini 2.0 Flash"),
    ],
}

PROVIDER_KEY_VAR: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "gemini":    "GEMINI_API_KEY",
}


def _available_suites() -> list[tuple[str, str]]:
    base = Path("fixtures")
    dirs = sorted(d for d in base.iterdir() if d.is_dir()) if base.exists() else []
    return [(str(d), d.name) for d in dirs] or [("fixtures/starter_v3", "starter_v3")]


# ── UI helpers ────────────────────────────────────────────────────────────────

def _pick(label: str, options: list[tuple[str, str]]) -> str:
    """Numbered menu; last option is always 'other / type your own'."""
    print(f"\n{label}")
    for i, (_, desc) in enumerate(options, 1):
        print(f"  {i}. {desc}")
    print(f"  {len(options) + 1}. Other (type your own)")
    while True:
        raw = input("  > ").strip()
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(options):
                return options[n - 1][0]
            if n == len(options) + 1:
                return input("  Enter value: ").strip()
        print(f"  Please enter a number between 1 and {len(options) + 1}.")


def _ask(prompt: str, default: str) -> str:
    raw = input(f"  {prompt} [{default}]: ").strip()
    return raw if raw else default


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n┌──────────────────────────────────┐")
    print("│   Nalana Eval  ·  Benchmark CLI   │")
    print("└──────────────────────────────────┘")

    # Step 1: provider
    provider = _pick("Which provider?", PROVIDERS)

    # Step 2: API key (skip for mock)
    api_key: str | None = None
    key_var: str | None = PROVIDER_KEY_VAR.get(provider)
    if key_var:
        api_key = os.environ.get(key_var, "").strip() or None
        if not api_key:
            api_key = getpass.getpass(f"\n  {key_var}: ").strip() or None
        if not api_key:
            sys.exit(f"\nError: {key_var} is required for {provider}.")

    # Step 3: model (from provider's list, or "mock" directly)
    if provider == "mock":
        model = "mock"
    else:
        model = _pick("Which model?", PROVIDER_MODELS[provider])

    # Step 4: suite
    suite = _pick("Which test suite?", _available_suites())

    # Step 5: cases + pass@k
    print()
    cases     = _ask("Number of cases (0 = all)", "0")
    pass_at_k = _ask("Attempts per case  (pass@k)", "3")

    # Step 6: judge model.  Default is gpt-4o (multimodal, see DECISIONS.md
    # ADR re: M3 evaluation).  Type "skip" to disable.  Suites with cases
    # whose `judge_policy: score` will silently produce no L3 score when
    # judge is disabled — we warn so the user notices.
    judge = _ask("Judge model (or 'skip' to disable)", "gpt-4o")
    if judge.strip().lower() in ("skip", "none", ""):
        judge = "skip"
        print("  ⚠ Judge disabled — any case with judge_policy=score will not "
              "receive an L3 score.")

    # Summary
    print("\n  ────────────────────────────────")
    print(f"  Provider  {provider}")
    print(f"  Model     {model}")
    print(f"  Suite     {suite}")
    print(f"  Cases     {'all' if cases == '0' else cases}")
    print(f"  pass@k    {pass_at_k}")
    print(f"  Judge     {judge}")
    if key_var and api_key:
        print(f"  {key_var[:16]:<16}  {api_key[:10]}...")
    print("  ────────────────────────────────")

    if input("\n  Run? [Y/n]: ").strip().lower() in ("n", "no"):
        sys.exit("\nAborted.")

    env = {**os.environ, "MODELS": model, "CASES": cases, "SUITE": suite}
    if key_var and api_key:
        env[key_var] = api_key

    # If the judge needs a different provider's key than the test model
    # (e.g. anthropic test model + gpt-4o judge), warn early — the judge
    # module will silently degrade to skip mode if the key is missing,
    # which is a frequent footgun.
    judge_key_var = (
        "OPENAI_API_KEY"      if judge.startswith(("gpt-", "o1", "o3", "o4")) else
        "ANTHROPIC_API_KEY"   if judge.startswith("claude-") else
        "GEMINI_API_KEY"      if judge.startswith("gemini-") else
        None
    )
    if judge != "skip" and judge_key_var and not os.environ.get(judge_key_var):
        print(f"  ⚠ Judge model '{judge}' needs {judge_key_var}, but it isn't "
              f"set in your shell. Judge calls inside the container will fail "
              f"and L3 scores will be N/A. Set it before running, or pick "
              f"'skip' for the judge.")

    cli_extra_args = ["--pass-at-k", pass_at_k]
    if judge == "skip":
        cli_extra_args.append("--no-judge")
    else:
        cli_extra_args += ["--judge-model", judge]

    print()
    result = subprocess.run(
        ["docker", "compose", "run", "--build", "--rm", "eval"] + cli_extra_args,
        env=env,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\n\nInterrupted.")
