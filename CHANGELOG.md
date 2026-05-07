# Changelog

Append-only log of significant changes to this repository.
One block per PR / milestone / decision. Reverse chronological (newest on top).

For details on any entry, follow the linked PR / handoff doc / ADR.

> Format note: this is **internal velocity**, not a user-facing release log. Brief is fine.

---

## 2026-05-06 — #15.2: existing-fixture audit (per ADR-005 strict mode)

Applies the per-case audit decisions locked in [`docs/handoffs/2026-05-02-15.2-audit-decisions.md`](docs/handoffs/2026-05-02-15.2-audit-decisions.md). All changes mechanical — no judgment beyond what the decisions doc already records.

Fixture taxonomy corrections (9 of 80 cases, replacing #15.1's `single_object` placeholder):
- `fixtures/starter_v3/ambiguous.json`:
  - **CV-AMB-002** (chair) → `composition`; `acceptable_styles` expanded to 6 styles
  - **CV-AMB-004** (house) → `composition`; `acceptable_styles` expanded to 6 styles
  - **CV-AMB-005** (open creative) → `multi_object`
- `fixtures/starter_v3/compositional.json`:
  - **CV-CMP-001** (cube + sphere) → `multi_object`
  - **CV-CMP-002** (3 primitives) → `multi_object`
  - **CV-CMP-003** (stack two cubes) → `composition`; `judge_policy: audit_only` → `score` (the only flip in the corpus); `acceptable_styles` expanded to 4 styles
  - **CV-CMP-004** (table) → `composition`; `acceptable_styles` expanded to 6 styles
  - **CV-CMP-005** (3-object scene) → `composition`; `acceptable_styles` expanded to 6 styles
- `fixtures/starter_v3/safety.json`:
  - **CV-SAF-004** (sphere + cube preserve) → `multi_object`

The other 71 cases retain `single_object` (the #15.1 mechanical placeholder is correct for them per audit §7).

CLI deprecation (deferred from #15.1 to avoid noisy intermediate state):
- `nalana_eval/cli.py` `--difficulty-dist` now emits a runtime deprecation warning and its help string is marked `[DEPRECATED, removal in v3.2]` per ADR-005. Functionality preserved through v3.1.

Cost impact (revising ADR-005 §Q5 projection):
- Audit moves only **1 case** to `judge_policy=score` (CV-CMP-003 from `audit_only`); the other 4 composition cases were already at `score`. Per-run cost rises ~$3 → ~$3.20 (≈+7%), not the projected ~3.5×. The dramatic ~$3 → ~$10 jump lands later, with the LLM-authored hard cases (#15.3+), not with this audit pass.

Refs: ADR-005, [docs/handoffs/2026-05-02-15.2-audit-decisions.md](docs/handoffs/2026-05-02-15.2-audit-decisions.md), [docs/handoffs/2026-05-06-15.2-audit.md](docs/handoffs/2026-05-06-15.2-audit.md). Unblocks #15.3 (LLM authoring CLI), #15.4 (drift checker), #15.5 (honeypot infrastructure).

---

## 2026-05-06 — PR-C: Xvfb stderr noise suppression

First of three split PRs replacing the original PR-B omnibus per ADR-003. Smallest of the trio — ships first to clear the plate.

`docker/entrypoint.sh`:
- Xvfb's own stdio redirected to `${XVFB_LOG:-/tmp/xvfb.log}`. Harmless `_XSERVTransmkdir` warnings (caused by `/tmp/.X11-unix` ownership mismatch under non-root `appuser`, see PR-A C5) no longer drown out benchmark output.
- New `_dump_xvfb_log` helper called on both existing startup-failure exit paths, preserving diagnosability.
- No new env flags; full diff is ~12 lines.

Sibling PRs to follow: PR-D (`attempts.csv` schema migration helper) and PR-E (L2 validator vocabulary + `CV-AMB-001` constraint tightening). All three address PR-A retrospective items deferred from the merge.

Refs: ADR-003, [docs/handoffs/2026-05-06-pr-c-xvfb-noise.md](docs/handoffs/2026-05-06-pr-c-xvfb-noise.md), [docs/handoffs/2026-04-29-post-merge-cleanup.md](docs/handoffs/2026-04-29-post-merge-cleanup.md) §6.

---

## 2026-05-02 — #15.1: schema fields (SceneComplexity / Provenance / Tag / draft) + mechanical fixture backfill

Per ADR-005, schema-level taxonomy lands. Pure infrastructure PR — no judgment-based data changes (those land in #15.2 audit).

Schema changes (`nalana_eval/schema.py`):
- New enums: `SceneComplexity` (single_object / multi_object / composition / full_scene), `Provenance` (handcrafted / synthetic / llm_authored), `Tag` (canonical / adversarial / ambiguous / honeypot)
- New required field on `TestCaseCard`: `scene_complexity: SceneComplexity = SINGLE_OBJECT` (default = safe placeholder; #15.2 corrects ~10-15 cases)
- New optional fields: `provenance: Provenance = HANDCRAFTED`, `draft: bool = False`, `tags: List[Tag] = []`
- Existing field `difficulty: Difficulty` made `Optional` (deprecated per ADR-005, removal in v3.2)

Existing 80 fixtures backfilled mechanically:
- All cases get `scene_complexity: "single_object"` (placeholder — #15.2 audit corrects the ~10-15 that should be multi_object/composition/full_scene)
- `starter_v3/*` cases get `provenance: "handcrafted"`; `synthetic/*` get `provenance: "synthetic"`
- All cases get `tags: ["canonical"]`

Tests (`tests/test_schema.py`):
- 14 new tests covering each new enum value, defaults, validation, deprecation back-compat
- All existing tests pass unchanged

Side cleanup:
- `docs/handoffs/2026-04-29-post-merge-cleanup.md` status flipped `in_progress` → `shipped` (PR-A merged 2026-04-30; this update was one of #21's bundled follow-ups)

Refs: ADR-005, #15.0 (covered by ADR-005 PR), #15.1 GitHub issue, [docs/handoffs/2026-05-02-15.1-schema-fields.md](docs/handoffs/2026-05-02-15.1-schema-fields.md). Blocks #15.2 (existing-fixture audit) and #15.3 (LLM authoring CLI).

---

## 2026-04-30 — ADR-005: TaskLength dropped, SceneComplexity added, L3 judge for spatial coherence

Doc-only PR. Taxonomy redesign of `TestCaseCard` axes feeding #13 (Test case authoring pipeline). Five linked decisions made via chat 2026-04-30:

- **Q1** `Difficulty` enum kept as deprecated `Optional` for one cycle; removal targeted at v3.2.
- **Q2** Proposed `TaskLength` axis dropped at design time. Histogram of all 80 existing prompts (shortest variant per case) clustered in 3-9 word range — axis would be a constant column with no signal. Original "Difficulty" intent of "step count" was the same v2 ground-truth-replication mental model V3 abandoned.
- **Q3** Spatial coherence on `SceneComplexity = composition` cases evaluated via L3 judge, NOT hard `relative_positions` constraints. Task #22 prototype confirmed judge can distinguish coherent vs incoherent outputs on non-empty scenes.
- **Q4** New `SceneComplexity` field is **manually authored** on `TestCaseCard`; not auto-derived from constraint shape. Decoupling preserves author intent and enables drift_check (#15.4) cross-validation.
- **Q5** #15.2 audit operates in **strict mode**: tag + flip `judge_policy=score` + expand `acceptable_styles` for COMPOSITION/FULL_SCENE cases all in one pass. Per-run cost rises ~3.5× (~$3 → ~$10 for 200-case run); accepted and documented.

Hard prerequisite for #15.2 enactment: `ian/judge-empty-scene-guard` PR must merge first (otherwise empty-scene hallucination contaminates new judge metrics).

Refs: ADR-005, [docs/handoffs/2026-04-30-adr-005-taxonomy.md](docs/handoffs/2026-04-30-adr-005-taxonomy.md), Task #22 prototype data (run `20260501_7d5bc27e`).

---

## 2026-04-29 — PR-A: post-merge cleanup + handover infrastructure

13-commit PR. Fixes from #18 review (Docker hardening, openai_runner, screenshot rendering) plus 4 process / docs files (this CHANGELOG, `CLAUDE.md`, `docs/handoffs/`, two new ADRs).

Highlights:
- **C0a** Add `CLAUDE.md` (AI onboarding entry); remove `AGENTS.md` from `.gitignore`.
- **C0b** Add `CHANGELOG.md`, `docs/handoffs/_TEMPLATE.md`, `docs/handoffs/2026-04-29-post-merge-cleanup.md`. Move `docs/HANDOFF_TASK_14.md` → `docs/handoffs/2026-04-28-wizard-cli-handoff.md` (status: shipped); delete `docs/HANDOFF_TASK_14.zh.md` (handoffs are EN-only).
- **C1** `screenshot.py` sets `shading.color_type='MATERIAL'` so the multimodal judge can see actual material colors.
- **C2** `bench.py` now defaults `--judge-model gpt-4o` (was `skip`); warns when `judge_policy=score` cases run with judge disabled.
- **C3** `--retry-with-feedback` opt-in flag (default OFF). `attempts.csv` gains `had_retry_context: bool` and `iterations_taken: int`.
- **C4** Fixture `CV-SAF-004` now requires the added sphere not to fully overlap the pre-existing cube (relative-position constraint).
- **C5** Dockerfile pins Blender 4.2.3 SHA256, adds `x11-utils`, runs as non-root `appuser` (UID 1000).
- **C6** `docker/entrypoint.sh` replaces `sleep 1` Xvfb race with `xdpyinfo` probe loop.
- **C7** New `tests/test_bench.py` covers happy path, invalid input, KeyboardInterrupt, declined-confirm.
- **C8** `docs/SYSTEM_MAP.md` (+ `.zh.md`) gains "Alternative front-doors" section documenting Docker + `bench.py`.
- **C9** ADR-003 `docs/DECISIONS.md`: mixed-concerns PRs forbidden going forward.
- **C10** ADR-004 `docs/DECISIONS.md`: retry-with-feedback default OFF; data-driven, gated on Task #13 hard-case re-evaluation.
- **C11** Skip retry only when `failure_reason` starts with `"API error:"`. Exclude mock model from rescue-rate statistics.

Refs: [docs/handoffs/2026-04-29-post-merge-cleanup.md](docs/handoffs/2026-04-29-post-merge-cleanup.md), ADR-003, ADR-004.

---

## 2026-04-28 — PR #21 (brian-test): Docker + interactive launcher

Headless Blender Docker pipeline (Ubuntu 22.04 + Blender 4.2.3 + Xvfb), interactive `bench.py` launcher with provider/model picker, agentic retry loop scaffolding. Major bundled PR — ADR-003 was authored after merge as a process correction.

Refs: PR #21, GitHub merge commit `98ce599`.

---

## 2026-04-27 — PR #16 (ian_workspace): SYSTEM_MAP + DECISIONS + first handoff doc

System knowledge base (`docs/SYSTEM_MAP.md` + SVG mind map), decision log (`docs/DECISIONS.md`), and first per-task handoff doc (later migrated to `docs/handoffs/2026-04-28-wizard-cli-handoff.md` in PR-A). All bilingual at the time; handoff converted to EN-only per ADR-003 follow-up.

Refs: PR #16.

---

## 2026-04-27 — V3.0 milestone (commit `c12fc84`)

Full rewrite from v2 ground-truth-replication system to V3.0 constraint-based evaluation. New tiered architecture: L1 (deterministic regression) + L2 (constraint validation, main benchmark) + L3 (LLM-as-Judge). Synthetic generator producing 50 deterministic primitive cases. 30 hand-authored starter cases across 6 categories.

Refs: ADR-001, ADR-002, [docs/DESIGN.md](docs/DESIGN.md).
