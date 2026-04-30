# Handoff: PR-A — post-merge cleanup + handover infrastructure

```yaml
status:        in_progress
owner:         ian + Claude Cowork
related_task:  #18, #19
related_pr:    (TBD on push)
date_opened:   2026-04-29
date_closed:   —
```

---

## 1. What this is

PR-A is a follow-up to brian-test PR #21 (merged 2026-04-28 as commit `98ce599`). It addresses Docker hardening, OpenAI runner reliability, multimodal-judge readiness, and **establishes the docs / process infrastructure that should have existed before PR #21** — so future bundled PRs become impossible (ADR-003) and retry-loop default behavior is data-grounded (ADR-004).

13 commits in one PR because the fixes share a single root context (post-PR #21 cleanup); ADR-003 still applies to *future* PRs from now on.

## 2. Why now — what triggered this

Three surfaces converged:

1. **`db/attempts.csv` retrospective + 4-29runs analysis** showed retry-with-feedback rescue rate is ~10% on real models, concentrated in one lucky run. Not the panacea PR #21's commit message implied. Need data-grounded default and proper telemetry.
2. **PR #21 review (Task #17)** flagged: missing Blender SHA256 verification, root-running container, Xvfb sleep race, gpt-5/o-series silent param drop, missing `bench.py` tests. None blocking but all should land before next benchmark cycle.
3. **Workbench renderer doesn't surface `material.base_color`** — discovered while inspecting CV-AMB-001 apple screenshot. Judge would be color-blind once enabled. Must fix before activating judge by default.

Plus: every prior PR has been a snowflake with no handoff doc and no centralized changelog. Process infrastructure (`CLAUDE.md`, `CHANGELOG.md`, `docs/handoffs/`) belongs in this PR so it's available from day one of post-#21 work.

## 3. Scope

```
In (13 commits):
  Process / docs (foundation)
    C0a — CLAUDE.md (AI onboarding); remove AGENTS.md from .gitignore
    C0b — CHANGELOG.md, docs/handoffs/_TEMPLATE.md, this handoff doc;
          move docs/HANDOFF_TASK_14.md → docs/handoffs/2026-04-28-wizard-cli-handoff.md
          (mark status: shipped); delete docs/HANDOFF_TASK_14.zh.md (handoffs EN-only)
  Code fixes (the 11 originally scoped under Task #18)
    C1  — screenshot.py: Workbench shading.color_type='MATERIAL'
    C2  — bench.py: default --judge-model gpt-4o + warn on judge_policy=score-with-skip
    C3  — --retry-with-feedback opt-in (default OFF) + had_retry_context + iterations_taken CSV cols
    C4  — fixture CV-SAF-004: add relative_position constraint
    C5  — Dockerfile: pin Blender SHA256 + non-root appuser + x11-utils
    C6  — entrypoint.sh: xdpyinfo probe loop replaces sleep 1
    C7  — tests/test_bench.py
    C8  — docs/SYSTEM_MAP.md + .zh.md: "Alternative front-doors" section
    C9  — docs/DECISIONS.md ADR-003: mixed-concerns PRs forbidden
    C10 — docs/DECISIONS.md ADR-004: retry default OFF; opt-in via flag; gated on Task #13
    C11 — retry-skip refinement: only skip on "API error:" prefix; exclude mock from stats

Out (explicitly deferred):
  - Retry-context message redesign         → wait for Task #13 hard-case data
  - Bilingual translation of CHANGELOG /
    handoffs                                → not worth doubled maintenance for internal velocity
  - bench.py model list pulled from runners
    factory                                 → low ROI, fixture-style refactor for later
  - Vision-feedback agent loop / Phase-2
    agent design                            → product roadmap, not eval scope
```

## 4. Decisions made

```
Q: retry-with-feedback default ON or OFF?
→ OFF. 40 real-model retries across 4-28 + 4-29 data → 3 saves (7.5%); 
  concentrated in 1 of 7 runs. Not robust enough to justify breaking V3 
  "fair single-shot comparison" semantics by default. ADR-004.

Q: Skip retry on PARSE_ERROR entirely (initial proposal)?
→ No. CV-AMB-004 and CV-SAF-004 in run 94b59e4e were genuine LLM JSON 
  formatting failures that retry rescued. Skip only when failure_reason 
  starts with "API error:" (auth/param config errors). C11 implements this.

Q: Include mock model in retry-rescue rate stats?
→ Exclude. Mock returns hardcoded output regardless of prompt; retry on 
  mock has 0 chance of changing outcome. Counting it inflated the prior 
  "0/55" that misled my earlier analysis. C11 implements this.

Q: One PR with 13 commits, or split process docs from code fixes?
→ One PR. The process docs (C0a/C0b) need to land alongside the code fixes 
  so the new ADR-003 / ADR-004 / handoff template are version-aligned with 
  the changes they govern. ADR-003 itself takes effect for *future* PRs.
```

## 5. How to verify

Code:
- [ ] `pytest tests/` passes (especially `tests/test_bench.py`)
- [ ] `python3 -m py_compile` clean on all modified Python files
- [ ] `docker build .` succeeds **after** `BLENDER_SHA256` is filled in (build-arg or Dockerfile edit)
- [ ] `bash -n docker/entrypoint.sh` clean
- [ ] After merge, run `python -m nalana_eval.cli --suite fixtures/starter_v3 --models claude-sonnet-4-6` (no `--retry-with-feedback`); `attempts.csv` has new columns; pass@1 == pass@3 (single-shot mode confirmed)
- [ ] Same run with `--retry-with-feedback`: `attempts.csv` `had_retry_context=True` on retry rows; pass@3 ≥ pass@1

Renderer:
- [ ] After C1, run apple case (CV-AMB-001) and inspect `screenshots/CV-AMB-001_attempt_0.png` — apple body should be visibly red, stem brown. (Pre-C1 it's all grey.)

Docs:
- [ ] `CLAUDE.md` exists at repo root
- [ ] `CHANGELOG.md` exists at repo root with PR-A entry
- [ ] `docs/handoffs/_TEMPLATE.md` and `docs/handoffs/2026-04-29-post-merge-cleanup.md` exist
- [ ] `docs/handoffs/2026-04-28-wizard-cli-handoff.md` exists with `status: shipped` (moved from `docs/HANDOFF_TASK_14.md`)
- [ ] `docs/HANDOFF_TASK_14.md` and `docs/HANDOFF_TASK_14.zh.md` no longer exist at old paths
- [ ] `docs/DECISIONS.md` has ADR-003 and ADR-004 appended

## 6. Known issues / TODOs / handoff to next

- **Task #13 hard cases will gate the retry-default re-evaluation.** ADR-004's "re-evaluation gate" requires ≥30 hard cases with attempt-0 fail rate ≥30%. Until those exist, retry stays opt-in.
- **Brian + his AI assistant must read `CLAUDE.md`** before the next PR. Worth a Slack mention when PR-A merges.
- **Workbench shading lockup:** if `shading.color_type='MATERIAL'` doesn't fully restore color in CI, fall back to `'OBJECT'` or use baked vertex color. C1 commit message will note this.
- **`AGENTS.md` removal from `.gitignore` is intentional** but if a per-user `AGENTS.md` becomes needed, use `.local-agents.md` or similar suffix instead.
- **`docs/handoffs/2026-04-28-wizard-cli-handoff.md` is migrated from `docs/HANDOFF_TASK_14.md`.** The old path is removed in C0b; any external reference (Slack link, GitHub URL, comment in another repo) to the old URL will 404 after merge. Inbound references inside this repo are updated in the same commit. The Chinese version `docs/HANDOFF_TASK_14.zh.md` is deleted (handoffs are EN-only per ADR-003 follow-up).

Follow-up tasks suggested:
- New task: "Task #13 follow-up — re-run retry ON/OFF benchmark on hard cases" (after #13 lands)
- New task: "Workflow skill set — `/handoff`, `/adr`, `/changelog`" (after process gets exercised a few weeks)

## 7. References

- PR #21 merge commit: `98ce599`
- Pre-loop diagnostic data: `docs/handoffs/PR-A_data/` (TBD: archive the 4-28 single-case debug runs + 4-29runs aggregate alongside this doc?)
- ADR-003 (mixed-concerns PR forbidden): `docs/DECISIONS.md`
- ADR-004 (retry default OFF, data-grounded): `docs/DECISIONS.md`
- Related: `docs/handoffs/2026-04-28-wizard-cli-handoff.md` (Wizard CLI handoff, shipped via PR #21 as `bench.py`)
- Related task: #13 (Test case authoring pipeline) — gates retry re-evaluation
