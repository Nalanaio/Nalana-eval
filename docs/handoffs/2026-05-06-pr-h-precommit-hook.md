# Handoff: PR-H — pre-commit hook + AI commit recipe rule

```yaml
status:        in_progress
owner:         ian + Claude Cowork
related_task:  internal #31 (no GitHub issue — cleanup-track PR per CLAUDE.md numbering convention)
related_pr:    (TBD on push)
date_opened:   2026-05-06
date_closed:   —
```

---

## 1. What this is

Tier 1 preventive tooling for the "commit landed on wrong branch" class of mistakes that hit three times in a single session today (twice on `main`, once on a stale topic branch), each costing a cherry-pick + reset round-trip. Adds a `pre-commit` hook that blocks direct commits on `main` / `master`, plus an AI-side rule in CLAUDE.md that mandates branch verification as the first step of any commit recipe. The hook is the backstop; the rule is for not slipping in the first place.

## 2. Why now — what triggered this

Three concrete events in today's session, all share the same root cause (`git checkout -b` was either forgotten or lost during paste):

1. **PR-G commit landed on `main`** — recovery: `git checkout -b` from current HEAD then `git reset --hard origin/main` on main. ~15 min wasted.
2. **PR-G push pushed empty branch** — discovered when GitHub compare showed "no changes". Recovery: same shape. ~15 min wasted.
3. **#15.2 commit landed on stale `ian/pr-g-sandbox-and-branch-rules`** — recovery: same shape. ~10 min wasted.

The post-incident discussion concluded these would all have been impossible (or instantly diagnosed) if (a) `git commit` on `main` were blocked by a hook, and (b) every AI-supplied commit recipe started with explicit branch verification.

## 3. Scope

```
In:
- scripts/git-hooks/pre-commit             — the hook script
- scripts/setup-git-hooks.sh               — idempotent installer for per-clone setup
- CLAUDE.md                                — new gotcha row + new "AI commit recipe
                                              always verifies branch first" sub-rule
- CHANGELOG.md                             — entry block
- docs/handoffs/2026-05-06-pr-h-precommit-hook.md  — this file

Out (deferred):
- Tier 3 ergonomics (gnb shell alias, git switch promotion)        — per-user config,
                                                                     not repo concern
- Pre-push hooks                                                    — paranoia tier;
                                                                     not warranted by
                                                                     today's incidents
- Branch protection rules on GitHub                                 — already in place;
                                                                     ian can't push to main
                                                                     directly (this PR
                                                                     handles the LOCAL
                                                                     gap, where `git
                                                                     commit` to main
                                                                     was the actual
                                                                     point of failure)
```

## 4. Decisions made

```
Q: Hook bypass mechanism — none, env var, or --no-verify?
→ --no-verify (git's standard). Preserves a single, well-known escape hatch.
  Custom env vars or interactive prompts add cognitive load.

Q: Block which branches?
→ main + master only. ian_workspace and other long-lived branches are
  legitimate commit targets per ian's workflow. Hardcoding the deny-list
  beats parameterizing it; the set is small and stable.

Q: Hook source location — track in repo or live only in .git/hooks/?
→ Track in scripts/git-hooks/, install via scripts/setup-git-hooks.sh.
  .git/hooks/ isn't git-tracked, so without a tracked source other
  contributors (Brian) won't get the hook on their clones. Tracked
  source + per-clone install script is the standard pattern.

Q: AI rule — bury in existing "Sync before reasoning" section, or new section?
→ Sub-rule inside the existing section. The "verify branch before commit"
  rule is conceptually the same family as "verify state before reasoning"
  — both about preventing decisions on stale/wrong assumptions. Keeping
  related rules together makes them easier to recall as a coherent set.
```

## 5. How to verify

- [ ] `bash scripts/setup-git-hooks.sh` from repo root prints `Installed: pre-commit` and exits 0
- [ ] `ls -la .git/hooks/pre-commit` shows the file is executable (`-rwxr-xr-x` or similar)
- [ ] On `main` branch with a dummy change: `git add foo && git commit -m test` → hook prints the error message and exits non-zero; no commit created (`git log` HEAD unchanged)
- [ ] On `main` with `--no-verify`: `git commit --no-verify -m test` → succeeds (then `git reset --hard HEAD~1` to undo the test)
- [ ] On a topic branch: `git commit -m test` → hook does not interfere
- [ ] CLAUDE.md gotcha table has the new "Direct commits to main / master are blocked" row
- [ ] CLAUDE.md "Sync before reasoning about git state" section now has a fourth sub-rule "AI commit recipe always verifies branch first"

## 6. Known issues / TODOs / handoff to next

- **Brian (and any future contributor) needs to run `bash scripts/setup-git-hooks.sh` once** after clone to get the hook. Worth a note when this PR merges. README could mention it under "First-time setup" if/when that section gets written; for now the gotcha row in CLAUDE.md and the install script's name are self-explanatory.
- **The AI rule is a self-imposed discipline, not enforceable** — no tool can verify the AI inserted `git branch --show-current` as the first line. Effectiveness depends on the AI re-reading CLAUDE.md per session-start workflow. The hook covers the user-side slip; the rule covers the AI-side slip. Both are needed.
- **`scripts/` directory is new in this PR** — repo previously had no `scripts/` folder. If a Python `scripts/` convention emerges later, the shell scripts here are still appropriate (shell hooks must be shell, not Python).
- **No pre-push hook**. We discussed but rejected — today's incidents were all `commit`-time, not `push`-time. Add later if pre-push slip ever happens.

## 7. References

- ADR-003 (one PR = one concern) — this PR's single concern is "preventive tooling for today's git mishaps"
- CLAUDE.md sections "Sync before reasoning about git state" / "Sandbox shell and the user's `.git/` don't mix" / "'Behind main' alone is not a delete signal" — the existing companion rules from earlier in today's session
- Today's three commit-mishap incidents:
  - PR-G commit on `main` (recovered via cherry-pick + reset)
  - PR-G empty push (recovered via re-commit on correct branch)
  - #15.2 commit on stale `ian/pr-g-sandbox-and-branch-rules` (recovered via cherry-pick onto fresh branch from main)
