# Handoff: Wizard CLI (Task #14)

```yaml
status:        shipped (with reduced scope — see "Implementation deviation" at end)
owner:         ian (handoff author) → Brian Chen (implementer)
related_task:  #14
related_pr:    #21 (merged 2026-04-28 as commit 98ce599)
date_opened:   2026-04-28
date_closed:   2026-04-28
```

> **Migrated 2026-04-29** from `docs/HANDOFF_TASK_14.md` to `docs/handoffs/2026-04-28-wizard-cli-handoff.md` (PR-A C0b). Chinese version (`HANDOFF_TASK_14.zh.md`) deleted — handoffs are EN-only by convention. Original spec preserved verbatim below; an "Implementation deviation" note is appended at the end documenting where Brian's actual `bench.py` differs from the spec.

> Notes for the engineer picking up Task #14 (`nalana-eval wizard` interactive subcommand). Self-contained — read this and `SYSTEM_MAP.md`, you have everything you need.

---

## TL;DR

You're building an interactive subcommand `nalana-eval wizard` that walks a user through configuring a benchmark run, then either prints the equivalent command or executes it. Think `npm init` or `create-react-app`'s prompt flow.

This work is **independent of #13** — you can start today. There's one small dependency that gets stitched in later (5-min follow-up); see "The #13 footnote" below.

**Estimated effort**: 0.5–1 day.

---

## Read these first (15 min orientation)

| Doc | Why |
|---|---|
| `docs/SYSTEM_MAP.md` | One-page overview of the 4-layer architecture. The wizard touches the cross-cutting CLI layer. |
| `docs/USAGE_GUIDE.md` (parameter table) | The 17 CLI flags the wizard needs to surface. Don't reinvent — mirror them. |
| `nalana_eval/cli.py` (existing code) | Subcommand structure. The wizard is one more subcommand alongside `history`, `review`, `calibrate`. |

You don't need to read DESIGN.md to do #14. It's a UX / scaffolding task, not an architecture change.

---

## What you're building

A CLI subcommand `python -m nalana_eval.cli wizard` that:

1. **Prompts the user interactively** for benchmark settings (questions listed below)
2. **Validates inputs** the same way the main CLI does (model name in known list, percentages sum to 1.0, etc.)
3. **Prints the equivalent `python -m nalana_eval.cli ...` invocation** so the user learns the flag form
4. **Optionally executes the run immediately** (one final yes/no prompt)

**Why we want this**: the main CLI has 17 flags. New users don't know which are required, which have sane defaults, or which combinations are valid. The wizard is a teaching tool that doubles as a runner.

---

## Files to create / modify

| File | Action | Notes |
|---|---|---|
| `nalana_eval/wizard.py` | **Create** | New module. Contains `run_wizard()` and helper prompt functions. |
| `nalana_eval/cli.py` | **Modify** | Register the `wizard` subcommand. Match the pattern used for `history`, `review`, `calibrate`. |
| `tests/test_wizard.py` | **Create** | Unit tests with `monkeypatch` on `input()` / `sys.stdin`. Cover happy path + invalid input handling. |
| `docs/USAGE_GUIDE.md` + `.zh.md` | **Modify** | Add a "Wizard mode" section near the top (right after Quick Reference). |
| `docs/USAGE_GUIDE.md` table | **Modify** | Add `wizard` to the Auxiliary CLIs table. |

**Don't touch** `schema.py`, `evaluator.py`, `judge.py`, `runners/`, `workers/`, `dispatcher.py`, `executor.py`, `screenshot.py`, `scene_capture.py`, `reporting.py`, `csv_db.py`. The wizard doesn't need any of them.

---

## Question flow (in order)

The wizard asks these in order. Each question shows a default the user can accept by hitting Enter.

| # | Question | Default | Validation |
|---|---|---|---|
| 1 | "Which model(s) do you want to test?" (comma-separated) | `gpt-5` | Must be in known model list (see `runners/__init__.py` factory) |
| 2 | "How many test cases?" | `30` (smoke test) | Positive integer, ≤ size of suite |
| 3 | "Suite to use?" | `fixtures/starter_v3` | Path must exist |
| 4 | "Difficulty distribution?" (e.g. `short:0.4,medium:0.4,long:0.2`) | `uniform` | Percentages sum to 1.0 ± 0.01 |
| 5 | "Pass@k?" | `3` | Integer in 1–10 |
| 6 | "Judge model? (or 'skip' to disable judge)" | `gpt-4o` | Must be in judge model list, or `skip` |
| 7 | "Number of workers?" | `cpu_count() * 0.75` | Integer 1–32 |
| 8 | "Output directory?" | `artifacts/` | Path is writable (create if missing) |
| 9 | "System prompt? (eval-default / nalana-prod)" | `eval-default` | One of the two enum values |
| 10 | "Print command, execute, or both?" | `both` | One of `print` / `execute` / `both` |

After question 10, print the assembled CLI line. If user chose execute or both, invoke the main benchmark function (don't shell out — call it as a Python function so errors propagate cleanly).

---

## Implementation hints

### Choosing a prompt library

You have three options. Pick **whichever is least friction**:

1. **Stdlib `input()`** — zero dependencies. Use this if you want to keep `requirements.txt` clean. You'll need to write your own validation loops (`while True: ... if valid break`).
2. **`questionary`** — modern, supports defaults / validators / arrow-key selects. Add to `requirements.txt`. Recommended.
3. **`inquirer`** — older alternative to questionary. Same idea.

If unsure, go with `questionary`.

### Mirror the existing CLI pattern

`cli.py` uses `argparse` with subparsers. The pattern for `history` / `review` / `calibrate` is roughly:

```python
# in cli.py
sub_wizard = subparsers.add_parser("wizard", help="Interactive setup wizard")
sub_wizard.set_defaults(func=run_wizard_cli)

def run_wizard_cli(args):
    from nalana_eval.wizard import run_wizard
    run_wizard()
```

### Validation hookup

Don't duplicate validation logic. Import the same validators the main CLI uses (e.g., model name lookup, distribution parser). If a validator doesn't exist as a standalone function yet, **extract it** from the main CLI to a shared util — that's a legitimate small refactor.

### Don't over-engineer

The wizard is a thin UX layer. **No state machines, no plugin system, no config-file persistence**. Just a sequence of questions → CLI string → optional invoke. ≤ 200 lines of `wizard.py` is the right ballpark.

---

## Acceptance criteria

You're done when:

- [ ] `python -m nalana_eval.cli wizard` launches the prompt flow
- [ ] All 10 questions ask in order with sensible defaults shown
- [ ] Hitting Enter on each question accepts the default
- [ ] Invalid inputs re-prompt with a clear error (don't crash)
- [ ] Final output is a copy-pastable `python -m nalana_eval.cli ...` line
- [ ] `execute` / `both` options actually run the benchmark
- [ ] `tests/test_wizard.py` covers: full happy path, invalid model name, invalid distribution sum, defaults-only run
- [ ] `pytest` passes
- [ ] `docs/USAGE_GUIDE.md` (and `.zh.md`) has a new "Wizard mode" section with an example session

---

## Local development

```bash
# Set up
cd ~/Nalana-eval
pip install -r requirements.txt    # (+ questionary if you go that route)

# Develop without burning API budget — use mock runner
export OPENAI_API_KEY=sk-fake
python -m nalana_eval.cli wizard
# When wizard asks for model, type: mock-model

# Run tests
pytest tests/test_wizard.py -v

# Test a real wizard → execute path with smoke-test budget
python -m nalana_eval.cli wizard
# Pick: gpt-5, 5 cases, simple-mode, judge=skip
```

---

## The #13 footnote (the only dependency)

A separate task (#13) is adding a `tags: List[Tag]` field to `TestCaseCard` schema, with values like `canonical`, `adversarial`, `ambiguous`, `multi_object`, `stylized`. This will let users filter the suite by tag.

**For now: do NOT prompt for tag filtering.** The schema doesn't have `tags` yet, so the field would be unfilterable.

**After #13 ships its schema change** (you'll see a new commit touching `nalana_eval/schema.py` to add the `Tag` enum and the `tags` field), come back and add a question between #5 (Pass@k) and #6 (Judge model):

> "Filter cases by tag? (canonical / adversarial / stylized / multi_object / skip)"

Read the available tag values from `Tag.__members__` so the question stays in sync if the enum grows. This is a 5–10 minute follow-up — open a separate small PR.

You'll know #13 is ready when:
- `Tag` enum is importable from `nalana_eval.schema`
- existing fixtures have non-empty `tags` arrays
- the main CLI accepts `--tags canonical,stylized`

---

## Git workflow

This repo uses one persistent branch (`ian_workspace`) for the current work, but you should open your own:

```bash
git checkout main
git pull
git checkout -b <yourname>/task-14-wizard
# ... commit as you go ...
git push -u origin <yourname>/task-14-wizard
```

Open a PR against `main` when acceptance criteria pass. Tag `@ian` (or whoever the current task-14 reviewer is) for review.

---

## Common gotchas

- **`cpu_count()` on M-series Macs reports performance + efficiency cores.** The default `cpu_count() * 0.75` over-allocates. The main CLI already has logic for this; reuse it, don't reinvent.
- **`input()` doesn't work in some IDE consoles.** Test from a real terminal, not from VS Code's "Run Python File" button.
- **Don't call `sys.exit()` inside the wizard.** Return a structured result. The CLI dispatcher decides whether to exit.

---

## Where to ask questions

- Architecture / design questions → check `docs/DESIGN.md` first, then ping `@ian`
- Specific Pydantic / schema questions → check `docs/SYSTEM_MAP.md` first, then ping `@ian`
- "Is this how the existing CLI handles X?" → grep `cli.py` first, then ping `@ian`
- Stuck for > 30 minutes → ping `@ian`. Don't spin.

PR conventions: small commits, descriptive messages, link this doc in the PR description so reviewers know the context.

Welcome aboard. 🚀

---

## Implementation deviation (added retroactively, 2026-04-29)

Brian shipped via PR #21 as `bench.py` at the repo root + Docker compose dispatch, **not** as a `nalana-eval wizard` subcommand. The implementation covers ~5 of the 10 specced questions. Below is the gap analysis; the remaining items are scoped into PR-B follow-up work alongside difficulty-vs-task-length redesign.

| Spec question | bench.py status | Gap impact |
|---|---|---|
| 1. Model | ✅ Improved (provider → model two-step) | none — better UX than spec |
| 2. Cases | ✅ asks (default `0` = all, instead of `30` smoke) | low — different default |
| 3. Suite | ✅ asks | none |
| 4. Difficulty distribution | ❌ not asked | medium — defaults to uniform; fixture is currently Short-heavy so sampling is skewed |
| 5. Pass@k | ✅ asks | none |
| 6. Judge model | ❌ not asked (defaults to `skip`) | **high** — users get no L3 judge unless they pass `--judge-model` directly. Fixed in PR-A C2 (default flipped to `gpt-4o`). |
| 7. Workers | ❌ not asked | medium — Docker uses simple-mode (1 worker), large runs slow |
| 8. Output dir | ❌ not asked | low — Docker volume is fixed mount; correct for Docker |
| 9. System prompt (eval-default vs nalana-prod) | ❌ not asked | medium — can't easily benchmark "with vs without Nalana production prompt" |
| 10. Print / execute / both | ❌ executes only | medium — loses the "learn the CLI flag form" teaching value |

**Architecture deviation:** standalone script + Docker dispatch, not a CLI subcommand. Trade-off: simpler for first-time users but couples wizard to Docker. Power users still use direct CLI. Reasonable for an MVP wizard.

**Other deviations:**
- Model list is hardcoded in `bench.py` (spec asked for pull from `runners/__init__.py` factory) — will go stale as new models ship.
- No `tests/test_bench.py` (spec required tests). Added retroactively in PR-A C7.
- No "Wizard mode" section in `USAGE_GUIDE.md` (spec required). Deferred to PR-B.
- Tag-filter follow-up (per spec) still pending Task #13.

**Why these are OK to defer:** Brian's design choice was a minimal-viable wizard that hands power-user controls back to direct CLI invocation. This is a reasonable UX pattern. The high-impact gap (judge default) is patched in PR-A C2; the rest collect into PR-B and will be re-scoped alongside the broader "difficulty vs task length" rethink.
