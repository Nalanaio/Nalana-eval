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

    # Summary
    print("\n  ────────────────────────────────")
    print(f"  Provider  {provider}")
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
