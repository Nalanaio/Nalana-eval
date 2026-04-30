"""Tests for the interactive `bench.py` launcher.

`bench.py` lives at the repo root; it's importable thanks to the sys.path
shim in the project-level `conftest.py`.

We exercise it by monkey-patching:
  - `builtins.input`            — answers come from a queue
  - `bench.subprocess.run`      — never actually launch docker
  - `bench.os.environ`          — control whether an API key is "already set"

The wizard's question order (post C2 — judge model added):
  1. provider                                    (_pick)
  2. API key inline if env var missing           (getpass)
  3. model (skipped for mock)                    (_pick)
  4. suite                                       (_pick)
  5. cases                                       (_ask)
  6. pass@k                                      (_ask)
  7. judge model                                 (_ask, default 'gpt-4o')
  8. confirm "Run? [Y/n]"                        (input)
"""
from __future__ import annotations

import getpass
import subprocess
from typing import Iterator, List

import pytest

import bench


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _input_factory(answers: List[str]):
    """Return a callable that pops answers from the queue in FIFO order.

    Raises if the script asks more questions than we provided answers for —
    that surfaces test-data bugs instead of silently hanging.
    """
    queue: Iterator[str] = iter(answers)

    def _input(prompt: str = "") -> str:  # noqa: D401
        try:
            return next(queue)
        except StopIteration as exc:
            raise AssertionError(
                f"bench.py asked for more input than test provided. "
                f"Prompt was: {prompt!r}"
            ) from exc

    return _input


def _patch_input(monkeypatch, answers, key: str | None = None):
    """Wire stdin answers into both `input()` and `getpass.getpass()`.

    bench.py uses `getpass` for API-key entry; tests need to supply that too
    when the corresponding env var is missing.
    """
    monkeypatch.setattr("builtins.input", _input_factory(answers))
    # When provided, supply the API key via getpass (the wizard prompts via
    # getpass for the secret rather than plain input). Single-shot.
    if key is not None:
        monkeypatch.setattr(getpass, "getpass", lambda prompt="": key)
    else:
        # Fall back to AssertionError if the wizard tries to ask via getpass
        def _no_getpass(prompt: str = "") -> str:
            raise AssertionError(
                f"bench.py called getpass for key but test did not provide one. "
                f"Prompt was: {prompt!r}"
            )
        monkeypatch.setattr(getpass, "getpass", _no_getpass)


@pytest.fixture
def fake_subprocess(monkeypatch):
    """Capture whatever bench.py would have shipped to docker compose."""
    calls: List[dict] = []

    class _Result:
        returncode = 0

    def _fake_run(cmd, env=None, **kwargs):  # noqa: ANN001
        calls.append({"cmd": list(cmd), "env": dict(env) if env else {}})
        return _Result()

    monkeypatch.setattr(bench.subprocess, "run", _fake_run)
    return calls


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_mock_provider_default_judge(monkeypatch, fake_subprocess):
    """Mock provider, accept default judge model (gpt-4o) — full happy path."""
    answers = [
        "1",          # provider = mock (first in PROVIDERS)
        "1",          # suite = first available
        "10",         # cases
        "3",          # pass@k
        "",           # judge — empty hits default 'gpt-4o'
        "y",          # confirm run
    ]
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY",   raising=False)
    monkeypatch.delenv("GEMINI_API_KEY",   raising=False)
    _patch_input(monkeypatch, answers)

    with pytest.raises(SystemExit) as excinfo:
        bench.main()

    assert excinfo.value.code == 0, "exit code should reflect subprocess.returncode"
    assert len(fake_subprocess) == 1, "exactly one docker compose invocation"

    call = fake_subprocess[0]
    assert "docker" in call["cmd"][0]
    assert "compose" in call["cmd"]
    assert "--pass-at-k" in call["cmd"]
    assert "3" in call["cmd"]
    # Default judge is gpt-4o, so --judge-model should be passed
    assert "--judge-model" in call["cmd"]
    judge_idx = call["cmd"].index("--judge-model")
    assert call["cmd"][judge_idx + 1] == "gpt-4o"
    assert "--no-judge" not in call["cmd"]
    assert call["env"]["MODELS"] == "mock"
    assert call["env"]["CASES"]  == "10"


def test_mock_provider_skip_judge(monkeypatch, fake_subprocess):
    """User can opt out of judge by typing 'skip' — verify --no-judge passed."""
    answers = [
        "1",          # provider = mock
        "1",          # suite
        "0",          # cases (all)
        "1",          # pass@k
        "skip",       # judge → disabled
        "y",          # confirm
    ]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _patch_input(monkeypatch, answers)

    with pytest.raises(SystemExit) as excinfo:
        bench.main()

    assert excinfo.value.code == 0
    call = fake_subprocess[0]
    assert "--no-judge" in call["cmd"]
    assert "--judge-model" not in call["cmd"]


def test_anthropic_with_env_key(monkeypatch, fake_subprocess):
    """If the env var is already set, the script must not prompt for it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fixture")
    monkeypatch.setenv("OPENAI_API_KEY",   "sk-judge-fixture")  # for judge

    answers = [
        "2",          # provider = anthropic
        "1",          # model = first claude option
        "1",          # suite
        "0",          # cases
        "1",          # pass@k
        "",           # judge default gpt-4o
        "y",          # confirm
    ]
    _patch_input(monkeypatch, answers)

    with pytest.raises(SystemExit) as excinfo:
        bench.main()

    assert excinfo.value.code == 0
    call = fake_subprocess[0]
    assert call["env"]["MODELS"].startswith("claude-")
    assert call["env"]["ANTHROPIC_API_KEY"] == "sk-ant-test-fixture"


def test_anthropic_prompts_for_missing_key(monkeypatch, fake_subprocess):
    """Without ANTHROPIC_API_KEY in env, bench should prompt for it via getpass."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-judge-fixture")  # for judge default

    answers = [
        "2",          # provider = anthropic
        "1",          # model
        "1",          # suite
        "0",          # cases
        "1",          # pass@k
        "skip",       # judge skip — keeps test simple
        "y",          # confirm
    ]
    _patch_input(monkeypatch, answers, key="sk-ant-prompted-fixture")

    with pytest.raises(SystemExit) as excinfo:
        bench.main()

    assert excinfo.value.code == 0
    call = fake_subprocess[0]
    assert call["env"]["ANTHROPIC_API_KEY"] == "sk-ant-prompted-fixture"


# ---------------------------------------------------------------------------
# Negative / boundary cases
# ---------------------------------------------------------------------------


def test_missing_api_key_aborts(monkeypatch):
    """Provider needs key, env empty, user gives empty key via getpass → abort."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    answers = [
        "3",          # provider = openai
    ]
    _patch_input(monkeypatch, answers, key="")  # empty getpass response

    with pytest.raises(SystemExit) as excinfo:
        bench.main()

    code = str(excinfo.value.code)
    assert "OPENAI_API_KEY" in code or "required" in code.lower()


def test_invalid_menu_choice_reprompts(monkeypatch, fake_subprocess):
    """Out-of-range and non-numeric input should re-prompt, not crash."""
    answers = [
        "99",         # invalid range
        "abc",        # non-numeric
        "1",          # finally pick mock
        "1",          # suite
        "0",          # cases
        "1",          # pass@k
        "skip",       # judge
        "y",          # confirm
    ]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _patch_input(monkeypatch, answers)

    with pytest.raises(SystemExit) as excinfo:
        bench.main()

    assert excinfo.value.code == 0


def test_decline_run_does_not_invoke_subprocess(monkeypatch, fake_subprocess):
    """Answering 'n' at the final confirm should abort before docker runs."""
    answers = [
        "1",          # provider = mock
        "1",          # suite
        "0",          # cases
        "1",          # pass@k
        "skip",       # judge
        "n",          # confirm -> No
    ]
    _patch_input(monkeypatch, answers)

    with pytest.raises(SystemExit):
        bench.main()

    assert len(fake_subprocess) == 0, "must not invoke docker after decline"


def test_keyboard_interrupt_clean_exit(monkeypatch):
    """Ctrl-C at any prompt should exit cleanly via the __main__ guard."""
    def _raise_ki(prompt: str = "") -> str:  # noqa: D401, ARG001
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", _raise_ki)

    # main() doesn't catch KeyboardInterrupt — that's done by the
    # `if __name__ == '__main__'` guard at the bottom of bench.py. Simulate it.
    with pytest.raises(SystemExit) as excinfo:
        try:
            bench.main()
        except KeyboardInterrupt:
            import sys
            sys.exit("\n\nInterrupted.")

    assert "Interrupted" in str(excinfo.value.code)
