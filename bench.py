#!/usr/bin/env python3
"""Interactive benchmark launcher.

Usage:
    python bench.py
"""
import os
import subprocess
import sys
from pathlib import Path

# ── known models ─────────────────────────────────────────────────────────────

MODELS = [
    ("mock",              "Mock runner       — no API key, instant"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 — needs ANTHROPIC_API_KEY"),
    ("claude-opus-4-7",   "Claude Opus 4.7   — needs ANTHROPIC_API_KEY"),
    ("gpt-5.5",           "GPT-5.5           — needs OPENAI_API_KEY"),
    ("gemini-2.5-pro",    "Gemini 2.5 Pro    — needs GEMINI_API_KEY"),
]

_KEY_PREFIXES = {
    "claude":  "ANTHROPIC_API_KEY",
    "gpt":     "OPENAI_API_KEY",
    "o1":      "OPENAI_API_KEY",
    "o3":      "OPENAI_API_KEY",
    "gemini":  "GEMINI_API_KEY",
}


def _api_key_var(model_id: str) -> str | None:
    for prefix, var in _KEY_PREFIXES.items():
        if model_id.startswith(prefix):
            return var
    return None


def _available_suites() -> list[tuple[str, str]]:
    base = Path("fixtures")
    dirs = sorted(d for d in base.iterdir() if d.is_dir()) if base.exists() else []
    return [(str(d), d.name) for d in dirs] or [("fixtures/starter_v3", "starter_v3")]


# ── UI helpers ────────────────────────────────────────────────────────────────

def _pick(label: str, options: list[tuple[str, str]]) -> str:
    """Numbered menu; last option is always 'custom'."""
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

    # Model
    model = _pick("Which model?", MODELS)

    # API key (prompt only if not already in environment)
    key_var = _api_key_var(model)
    api_key: str | None = None
    if key_var:
        api_key = os.environ.get(key_var, "").strip() or None
        if not api_key:
            api_key = input(f"\n  {key_var}: ").strip() or None
        if not api_key:
            sys.exit(f"\nError: {key_var} is required for {model}.")

    # Suite
    suite = _pick("Which test suite?", _available_suites())

    # Cases + pass@k
    print()
    cases    = _ask("Number of cases (0 = all)", "0")
    pass_at_k = _ask("Attempts per case  (pass@k)", "3")

    # Summary
    print("\n  ────────────────────────────────")
    print(f"  Model     {model}")
    print(f"  Suite     {suite}")
    print(f"  Cases     {'all' if cases == '0' else cases}")
    print(f"  pass@k    {pass_at_k}")
    if key_var and api_key:
        print(f"  {key_var[:16]:<16}  {api_key[:10]}...")
    print("  ────────────────────────────────")

    if input("\n  Run? [Y/n]: ").strip().lower() in ("n", "no"):
        sys.exit("\nAborted.")

    env = {**os.environ, "MODELS": model, "CASES": cases, "SUITE": suite}
    if key_var and api_key:
        env[key_var] = api_key

    print()
    result = subprocess.run(
        [
            "docker", "compose", "run", "--build", "--rm", "eval",
            "--pass-at-k", pass_at_k,
        ],
        env=env,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\n\nInterrupted.")
