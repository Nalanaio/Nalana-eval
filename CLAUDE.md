# CLAUDE.md — AI Assistant Onboarding

> **First file any AI assistant should read when entering this repository.**
> Humans: skip to `README.md`. AI: keep reading — this defines how you should behave in this repo.

---

## What this repo is

**Nalana Eval V3.0** — an evaluation system for LLM × Blender 3D modeling. It tests how well LLMs (GPT, Claude, Gemini, …) generate Blender JSON operations from natural-language prompts.

The evaluation runs in three tiers (L1 / L2 / L3). Full architecture: [`docs/SYSTEM_MAP.md`](docs/SYSTEM_MAP.md).

This is **not** the Nalana product itself — it's a standalone testing tool.

---

## Mandatory reading order

Before making any change, read in order:

1. **[`docs/SYSTEM_MAP.md`](docs/SYSTEM_MAP.md)** — 4-layer architecture (M1 Inputs / M2 Execution / M3 Evaluation / M4 Outputs). Tells you what files do what.
2. **[`docs/DECISIONS.md`](docs/DECISIONS.md)** — Architecture Decision Records (ADRs). Explains *why* the codebase is the way it is. Don't undo a decision without reading the relevant ADR.
3. **[`docs/handoffs/`](docs/handoffs/)** — Anything in this folder marked `Status: in_progress` is current work. Don't conflict with it.
4. **[`CHANGELOG.md`](CHANGELOG.md)** — last ~20 entries. 30-second read.
5. **TodoList** (Cowork) / open tasks — to see what's currently active.

---

## Workflow rules (you must follow)

### Every work item maps to a Task entry

| When | Action |
|---|---|
| Decide to start a new piece of work | `TaskCreate` (status `pending`) |
| Actually start coding | `TaskUpdate` → `in_progress` |
| Scope or plan changes | `TaskUpdate` description |
| Done | `TaskUpdate` → `completed`, add `CHANGELOG.md` entry |
| Blocked / abandoned | `TaskUpdate` description with reason; don't delete |

The TaskList **is** the source of truth for "what's in flight." Keep it accurate.

### Every PR / significant change gets a handoff note

Create `docs/handoffs/<short-name>.md` from `docs/handoffs/_TEMPLATE.md`. Fill sections 1–4 at planning time, sections 5–7 at completion. Link this file in the PR description.

This is how the next person (or their AI assistant) understands what you did and why — without scrolling through commits.

### Issue / task numbering convention

There are three independent numbering systems. Don't conflate them.

| System | Looks like | Where it lives | Use in writing |
|---|---|---|---|
| **GitHub epic / sub-issue** | `#15`, `#15.1`, `#15.2`, … `#15.12` | GitHub project board, PR titles, branch slugs | **Default** — chat, PR titles, handoff docs, CHANGELOG, commit messages |
| **Internal Cowork TaskList ID** | `#21`, `#24`, `#25`, … | Cowork TaskList only | Internal todo tracking — **never** in PRs / commits / docs |
| **Doc section numbers** | `13.1`, `13.2`, … inside `TEST_CASE_AUTHORING.md` | The doc itself (it's chapter 13) | Don't rename — they're document structure, not task IDs |

GitHub assigns numbers project-wide as issues are created, so its numbers race ahead of any "internal milestone" numbering you might be tempted to use. Always reference work by GitHub number once an issue exists.

**Mapping for the case-authoring epic** (because old artifacts use the obsolete shorthand):
- Internal task tracker `#13` ≡ GitHub epic `#15` ≡ "Test case authoring pipeline"
- Sub-issues `#15.1`–`#15.12` ≡ project-board numbers `#26`–`#37` (don't use the latter; the dotted form is more readable)
- Old `#13.x` shorthand from before 2026-05-06 has been renamed in repo. Bare `#13` may still appear in older handoff docs as historical mention; don't go reformatting history.

**Cleanup-track PRs** (`PR-C`, `PR-D`, `PR-E`, …) without a GitHub issue use the letter shorthand instead. That's fine — they're small, ephemeral, and the linked handoff doc carries the context.

### One PR = one concern (ADR-003)

Bundling unrelated changes in one PR makes attribution impossible. The retry-loop / prompt-fix / API-fix bundle in PR #21 is the cautionary tale — see [ADR-003](docs/DECISIONS.md). When in doubt, split.

Bug fixes can be combined **only if they share a root cause**.

### Don't break L2 / L3 separation (ADR-004)

- **L2** (constraint validation, `nalana_eval/evaluator.py`) is the objective benchmark. Output is deterministic given fixture + scene snapshot.
- **L3** (LLM judge, `nalana_eval/judge.py`) is a *soft signal*. Output is probabilistic.

**Never feed L3 judge scores back into L2 pass/fail logic, retry triggers, or score aggregation.** Loop mechanisms can use L2 constraint failure reasons as feedback to the model — they cannot use judge output.

### Bilingual docs convention

User-facing docs are EN primary + `<name>.zh.md` Chinese mirror.

| Doc type | Bilingual? |
|---|---|
| `README`, `DESIGN`, `USAGE_GUIDE`, `SYSTEM_MAP`, `DECISIONS` | Yes — keep `.zh.md` in sync |
| `CHANGELOG`, `CLAUDE.md`, `docs/handoffs/<date>-<desc>.md` | EN-only by convention (internal velocity > polish) |
| `ARCHITECTURE`, `TEST_CASE_AUTHORING`, `CSV_SCHEMA`, `MIGRATION_FROM_V2`, `IMPLEMENTATION_BRIEF`, `calibration/README` | Currently Chinese-only — translation pending (see Task #11 follow-up) |

When editing a doc that has a `.zh.md` sibling, update **both**.

---

## Communication style (this repo)

These apply to every contributor regardless of who you're talking to:

- **Direct and concise.** Skip apologies, hedging, fluff.
- **Push back when you disagree** — back it with data, not gut feel.
- **Prefer specific recommendations** over open-ended questions. "Pick A or B" beats "what should I do?"
- **Self-correct explicitly** when new data invalidates an earlier conclusion. Don't quietly retract — call it out.
- **Use technical terms precisely.** Don't apply "agentic" / "intelligent" / "smart" to non-agentic features. ADR-004 is the cautionary case.
- **Mention cost / latency** when scope changes meaningfully affect run cost (>2× delta is the usual threshold).

## Language matching (per-user)

The repo has multilingual contributors. **Match the working language of whoever you're talking to** — usually whatever language they wrote their first message in:

- ian (primary maintainer) writes in Chinese — reply in Chinese.
- Brian + most other contributors write in English — reply in English.
- Code, commit messages, file contents, doc files: **always English** regardless of who you're talking to. The bilingual-mirror convention (`<doc>.zh.md`) is the only exception.

If unsure on a fresh session, mirror the user's first message. Don't ask "what language should I reply in?" — that's friction.

For more elaborate per-user preferences (editor tabs, indent style, naming conventions), use `.claude/settings.local.json` (gitignored, per-user). Don't expand this CLAUDE.md with user-specific knobs.

---

## Repo-specific gotchas

| Gotcha | Where |
|---|---|
| Don't reuse the production XML-RPC channel for evals | DESIGN.md §5.3 |
| Workbench renderer ignores `material.base_color` by default — must set `shading.color_type = 'MATERIAL'` | `nalana_eval/screenshot.py` |
| gpt-5 / o-series ignore `temperature` and `seed` parameters | `nalana_eval/runners/openai_runner.py` `_RESTRICTED_PREFIXES` |
| Mock model has hardcoded output — **exclude from retry-rescue / variance / cost statistics** | `nalana_eval/runners/mock_runner.py` |
| Docker container `db/` is **separate** from host `~/Nalana-eval/db/`. When analyzing retry stats etc., gather from BOTH | mount config in `docker-compose.yml` |
| Some pre-`98ce599` runs may have stale schema columns; reading old reports may need null-safe access | — |
| `.claude/` and `.env` are local secrets, gitignored. `AGENTS.md` and `CLAUDE.md` are **version controlled** — they are documentation, not config. | `.gitignore` |

---

## When you start a new Cowork session

1. Open with: *"Loading context from `CLAUDE.md`, `docs/handoffs/`, and TaskList — what's today's focus?"*
2. Run `TaskList` to see open tasks.
3. Skim any `docs/handoffs/<X>.md` whose front-matter shows `Status: in_progress`.
4. Skim last 5 `CHANGELOG.md` entries.
5. Confirm focus with user before doing tool calls.

If user says *"continue from session X"* — read transcript via `mcp__session_info__read_transcript(session_id=X)` and pick up. Don't speculate; ask if anything is ambiguous.

### Sync before reasoning about git state

**The Cowork sandbox cannot reach `github.com` (proxy 403 on `git fetch`).** Whatever the AI sees about branches, merge state, and `main`'s file content reflects the user's **last `git pull` only**. Acting on a stale view will silently produce wrong cleanup commands and wrong "is the codebase clean?" verdicts.

Cautionary case (2026-05-06): the rename PR was merged on remote with **unresolved conflict markers** (the user thought the GitHub web conflict editor had resolved them, but the commit went through with `<<<<<<<` / `=======` / `>>>>>>>` lines in `CHANGELOG.md`). The AI reviewed a stale local `main` from before the merge and reported the codebase as clean, missing the broken state. Only after the user ran `git pull` did the conflict markers surface.

Hard rule for the AI: **before running, recommending, or evaluating any command that depends on remote git state (branch lists, `main` content, "is X merged"), ask the user to run `git fetch origin --prune && git pull` first**, and base decisions on the post-pull output. After any git operation that resolves conflicts (especially via the GitHub web UI), grep the touched files for `^<<<<<<< `, `^======= *$`, `^>>>>>>> ` before declaring the work done.

Hard rule for the user: **after any merge happens via GitHub UI, run `git fetch origin --prune && git pull` locally before asking the AI to verify the result.** When resolving a merge conflict via the web UI, double-check the file preview for stray conflict markers before clicking *Mark as resolved*.

---

## Skill / slash-command availability (Cowork)

Planned but not yet implemented. Use the markdown templates manually:

| Slash | What it would do | Manual fallback |
|---|---|---|
| `/handoff` | generate handoff note from current diff + active task | copy `docs/handoffs/_TEMPLATE.md`, fill in |
| `/adr` | format a decision into ADR entry, append to `DECISIONS.md` | copy ADR-003's structure, append by hand |
| `/changelog` | extract changelog block from recent commits | edit `CHANGELOG.md` manually |

---

## Last updated

> 2026-05-06 by ian + Claude (added "Sync before reasoning about git state" rule + cautionary case).
> 2026-05-06 by ian + Claude (added "Issue / task numbering convention" section).
> 2026-04-29 by ian + Claude (PR-A C0a, initial draft).

Update this line on every change to this file.
