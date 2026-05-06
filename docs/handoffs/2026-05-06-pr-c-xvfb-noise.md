# Handoff: PR-C — Xvfb stderr noise suppression

```yaml
status:        in_progress
owner:         ian + Claude Cowork
related_task:  #21 (PR-A follow-up umbrella; sub-task internally #25)
related_pr:    (TBD on push)
date_opened:   2026-05-06
date_closed:   —
```

> First of three split PRs replacing the original "PR-B" omnibus per ADR-003.
> Sibling PRs: PR-D (CSV migration helper), PR-E (L2 validator vocabulary +
> CV-AMB-001 fixture). Each ships independently.

---

## 1. What this is

PR-A C5 made the container run as non-root `appuser`. PR-A C6 replaced the
`sleep 1` Xvfb race with an `xdpyinfo` probe loop. What neither commit
addressed: Xvfb itself emits harmless stderr warnings on startup
(`_XSERVTransmkdir: Owner of /tmp/.X11-unix should be set to root`, etc.)
because the `/tmp/.X11-unix` directory's ownership doesn't match the
non-root UID. These warnings drown out actual benchmark output. PR-C
redirects Xvfb's stdio to a log file and dumps it only on startup failure.

## 2. Why now — what triggered this

Flagged in PR-A retrospective as one of three deferred follow-ups (see
`docs/handoffs/2026-04-29-post-merge-cleanup.md` §6 reference / CLAUDE.md
gotchas). Original plan was to bundle into a single "PR-B"; per ADR-003
that bundling itself was the lesson, so it's split. PR-C is the smallest
of the three — ships first to clear the plate.

## 3. Scope

```
In:
- docker/entrypoint.sh — redirect Xvfb stdio to ${XVFB_LOG:-/tmp/xvfb.log};
                        add _dump_xvfb_log helper invoked on the two existing
                        startup-failure exit paths
- CHANGELOG.md         — one entry block
- this handoff doc

Out (deferred to sibling PRs):
- attempts.csv schema migration helper            → PR-D
- L2 validator vocabulary + CV-AMB-001 collection → PR-E
- Anything not strictly Xvfb stdio
```

## 4. Decisions made

```
Q: Suppress all Xvfb stderr, or filter the specific known-noise lines?
→ Suppress all (redirect to log file). Filtering by message string is
  brittle across Xorg versions; full redirect with on-failure dump preserves
  full diagnosability without runtime cost. The `_XSERVTransmkdir` warning
  is the *primary* known noise but not the only one — filter list would
  drift.

Q: Make verbose mode opt-in via env var?
→ No. YAGNI. If someone needs to see Xvfb output during a successful run,
  they can `cat /tmp/xvfb.log` from inside the container or override
  XVFB_LOG to /dev/stderr. No new flag in this PR.

Q: Add Xvfb log to artifact dir for CI?
→ No. Out of scope. If CI needs persistent Xvfb logs, that's a separate
  ops task — entrypoint shouldn't decide artifact retention policy.
```

## 5. How to verify

- [ ] `bash -n docker/entrypoint.sh` — clean (already verified)
- [ ] `docker build .` — succeeds (no Dockerfile changes; mainly a sanity check)
- [ ] Run a benchmark in container with `MODELS=mock CASES=2`:
  - [ ] No `_XSERVTransmkdir` warning visible in container stdout/stderr
  - [ ] Benchmark output (model rows, pass@1) visible un-cluttered
  - [ ] `/tmp/xvfb.log` exists inside container with the suppressed warnings
- [ ] Negative path (manual): force Xvfb to fail (e.g., kill Xvfb mid-startup
      via a hostile change, or set `-screen 0 0x0x0`); verify the
      `--- Xvfb log ---` block appears on stderr followed by the dumped log

## 6. Known issues / TODOs / handoff to next

- **No `XVFB_VERBOSE` env knob** — opted out per Decision §4 above. Add only
  when there's an actual user request.
- **Log file is not rotated.** Single Xvfb session writes once; container
  exit cleans /tmp. No need for rotation. If someone runs the container in
  a long-lived loop (not how we use it), they could fill /tmp; revisit then.
- **Sibling PRs (PR-D, PR-E)** are tracked separately. Don't touch CSV
  schema or L2 validators in this PR.

## 7. References

- ADR-003 (mixed-concerns PR forbidden) — `docs/DECISIONS.md`
- PR-A handoff: `docs/handoffs/2026-04-29-post-merge-cleanup.md` (§6 names
  this as deferred follow-up)
- CLAUDE.md gotcha row: "Xvfb noise" entry referenced internally
- Sibling tasks (internal): #27 (PR-D), #28 (PR-E), #26 (paper-only L2
  vocabulary design)
