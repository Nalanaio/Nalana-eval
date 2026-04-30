# Handoff: <short-title>

```yaml
status:        in_progress | shipped | abandoned
owner:         <name + AI tool, e.g. "ian + Claude Cowork">
related_task:  #<task_id>
related_pr:    #<PR number, when it exists>
date_opened:   YYYY-MM-DD
date_closed:   YYYY-MM-DD          # fill on shipped/abandoned
```

> Front-matter above is the canonical state. Keep it accurate as work progresses.

---

## 1. What this is (≤5 sentences)

One paragraph. *What* you're doing and *why now*. No history lectures.

## 2. Why now — what triggered this

Cite the source: which `report.json`, which ADR, which user complaint, which PR review thread, which observed bug. Link to it.

If this came from a meeting / Slack discussion, note who, when, and the upshot.

## 3. Scope

What's in. What's deliberately out. Be explicit about *not done* — the next person reading this needs to know what's still owed.

```
In:
- File X: change Y
- New module Z

Out (deferred):
- Related thing W (reason: …, tracked as Task #…)
```

## 4. Decisions made

Key forks in the road and which way you went. Brief. Link to ADRs if formalized.

```
Q: A or B?
→ Chose A because <one-line reason>. ADR-XXX if relevant.
```

## 5. How to verify (acceptance checklist)

Fill at planning time. Tick at completion.

- [ ] Concrete check 1 (e.g., `pytest tests/test_X.py` passes)
- [ ] Concrete check 2 (e.g., `docker build` succeeds with new Dockerfile)
- [ ] Concrete check 3 (e.g., manual: run benchmark and confirm `report.md` has new section)

## 6. Known issues / TODOs / handoff to next

What's not perfect yet, what to circle back to, what the next person should pick up.

```
- TODO #1: …
- Limitation: …
- Follow-up task suggested: #…
```

## 7. References

- PR: #…
- Commits: hash1, hash2, …
- ADRs: ADR-XXX, ADR-YYY
- External discussions: …
- Related handoffs: docs/handoffs/<other>.md
