# Paper-only: L2 validator vocabulary design

```yaml
status:        decisions_locked (awaiting PR-E implementation, task #28)
owner:         ian + Claude Cowork
related_task:  internal #26 (paper) / #28 (implementation, blocked on this doc)
related_pr:    (TBD on push — small paper PR, no code)
date_opened:   2026-05-06
date_closed:   —
```

> **This is a paper-only decisions doc, not a PR handoff.** It captures the
> L2 validator vocabulary design discussed today (in the CV-AMB-001
> "fixture too loose" exchange), so when PR-E (task #28) implements
> the actual validators + tightens CV-AMB-001, the spec is paste-ready
> with no re-derivation.

---

## 1. What this is

A vocabulary of L2 (deterministic constraint) validators expressing **"is the model's output a plausible candidate answer at all?"** — independent of whether it's the *right* answer (that's L3 judge territory). Triggered by the discovery that `CV-AMB-001` (Create an apple) has L2 constraints so loose (`mesh_object_count.minimum: 1`) that virtually any geometry passes, leaving all quality assessment to L3 alone — an L2/L3 separation smell.

The doc defines three new constraint primitives + a thin "validator helper" abstraction layer that wraps them in semantic names. The principle running through all of it: **L2 sets lower bounds, never upper bounds.** Upper bounds kill creative interpretations (the chair / table / house cases). Lower bounds catch garbage (empty scene, flat plane, off-by-orders-of-magnitude scale).

## 2. Why now — what triggered this

Mid-session discussion 2026-05-06 about whether to tighten `CV-AMB-001`'s constraints to filter genuinely bad outputs. Initial proposal was `mesh_count: {min: 1, max: 3}` — rejected by ian on the grounds that LLMs might legitimately use 5-mesh stylized apples or 1-mesh metaball variants; upper bounds penalize creative interpretation. The reframing crystallized: L2 should set floors (this isn't garbage), L3 should evaluate ceilings (this is good).

PR-E (task #28) was supposed to implement "tighten CV-AMB-001 constraints" but the right move turned out to be larger: introduce a generic validator vocabulary that CV-AMB-001 and many future cases can compose, instead of hand-rolling constraint shapes per case. PR-E now has two halves: (a) implement the new primitives + helpers (this doc's content), (b) apply to CV-AMB-001 as first user.

## 3. Scope

```
In (this doc — paper only):
- The three new constraint primitives, their JSON shape, semantics, validation logic
- The validator helper abstraction layer (semantic wrappers)
- Design principles (lower bounds only, exception for unit-sanity max)
- CV-AMB-001 specific prescription
- Implementation hints for PR-E (file locations, test cases)

Out (deferred to PR-E, task #28):
- Actual schema.py additions for the new constraint shapes
- Actual validator helper functions in a new module
- Unit tests for each primitive + helper
- CV-AMB-001 fixture edit applying the helpers
- CHANGELOG entry + handoff doc for PR-E

Out (deferred to broader case-authoring epic):
- Applying assert_dominant_mesh to "looks-like-X with clear main body"
  cases (a chair, a table) — those fixtures are already in #15.2 audit
  shape; the helpers can be retro-fitted later without a fixture rewrite
- A general fixture lint that flags cases using only mesh_count without
  any non_degenerate / scale check — paper-only design, not in this doc
```

## 4. Design principles

```
P1. L2 = "is this a plausible answer at all?"
    L3 = "is this the right answer?"
    Don't conflate.

P2. Lower bounds only. Upper bounds on mesh count / part count / etc.
    penalize creative interpretation (5-mesh stylized apple should
    pass; LLM authored a more elaborate model than minimum, that's not
    a failure).

P3. One exception to P2: scene_bounding_box.max_dimension.
    A scene at coordinates (10000, 10000, 10000) is almost certainly
    a unit error / hallucination, not a creative choice. Sanity max
    is allowed where the upper-bound semantic is "this can't be right"
    not "this is too elaborate".

P4. Validator helpers compose; they're not new constraint types.
    The three primitives (B / C / D) are the JSON schema additions;
    the helpers (assert_*) are Python convenience wrappers that
    write the primitives into a case's constraints. Author writes
    `["assert_geometry_exists", "assert_reasonable_scale"]`, the
    helper layer expands to the underlying primitives. Fewer JSON
    knobs per case → less per-case design work → less inconsistency
    across the corpus.

P5. ADR-004 (L2/L3 separation) is not weakened by this work.
    All three new primitives are deterministic given a scene snapshot.
    No judge call, no probabilistic logic. L3 still owns "looks like
    an apple"; L2 now also catches "doesn't look like geometry at all".
```

## 5. The three new constraint primitives

### B. `non_degenerate_mesh_count`

Same shape as the existing `mesh_object_count` constraint, but only counts meshes whose bounding box has all three dimensions ≥ ε (default `ε = 0.01`).

```jsonc
"hard_constraints": {
  "non_degenerate_mesh_count": {
    "minimum": 1,
    "epsilon": 0.01    // optional; default 0.01 if omitted
  }
}
```

**What it catches:** a "1 mesh exists" output that's actually a flat plane (z-extent 0), a thin line, or a degenerate-to-point object. Without B, these pass `mesh_object_count.minimum: 1`.

**What it doesn't:** the mesh's *shape correctness* (judge's job). A non-degenerate cube definitely passes B regardless of whether the prompt asked for a sphere.

### C. `scene_bounding_box`

A constraint on the union of all mesh bounding boxes in the final scene.

```jsonc
"hard_constraints": {
  "scene_bounding_box": {
    "min_volume": 0.001,       // optional; catches all-degenerate scenes
    "max_dimension": 50.0      // optional; catches unit-error / hallucination
  }
}
```

**What it catches:**
- `min_volume`: an entire scene of microscopic / collapsed meshes (everything passes B individually but the whole thing is still tiny / on top of each other).
- `max_dimension`: an output placing meshes at unreasonable coordinates (single-axis or aggregate). Standard Blender scenes are scale ~1-10; >50 is virtually always a unit error.

**Both fields optional** — author picks which sanity check applies. Per P3, this is the one constraint with an upper bound, justified.

### D. `concept_carrier_exists`

At least one mesh's bounding box volume must be ≥ `min_ratio` of the scene's total BB volume.

```jsonc
"hard_constraints": {
  "concept_carrier_exists": {
    "min_dominant_ratio": 0.15    // default 0.15
  }
}
```

**What it catches:** the output is "a bunch of thin decorative bits with no main body" — passes B and C individually but fails the "is there a concept-bearing main shape?" check.

**Use sparingly.** Appropriate for cases like "a chair / a table / a house" where there's a clear main body. **Not appropriate** for cases like CV-AMB-001 "an apple" (could legitimately be 8 evenly-sized metaballs) or `CV-CMP-005` "a miniature scene with 3 objects" (no single object should dominate).

This is the most semantically loaded of the three primitives; it embeds an assumption ("a main body exists") that not every case wants. Document per-case.

## 6. Validator helper layer

A thin Python layer wrapping the three primitives into named, composable checks. Authors write helper names in fixture JSON; the helper layer expands to the underlying primitives.

### Proposed module location

```
nalana_eval/constraints/standard_validators.py
```

Exposes three helper functions (or factory style, see §8):

```python
def assert_geometry_exists() -> Dict[str, Any]:
    """Returns the constraint dict for: at least 1 non-degenerate mesh."""
    return {
        "mesh_object_count": {"minimum": 1},
        "non_degenerate_mesh_count": {"minimum": 1},
    }

def assert_reasonable_scale(max_dim: float = 50.0,
                             min_vol: float = 0.001) -> Dict[str, Any]:
    """Returns the constraint dict for: scene within sensible scale bounds."""
    return {
        "scene_bounding_box": {
            "min_volume": min_vol,
            "max_dimension": max_dim,
        }
    }

def assert_dominant_mesh(min_ratio: float = 0.15) -> Dict[str, Any]:
    """Returns the constraint dict for: a concept-bearing main mesh exists.
    Use only for cases with a clear primary body (chair, table, house).
    NOT for ambiguous/distributed cases (apple, miniature scene)."""
    return {
        "concept_carrier_exists": {"min_dominant_ratio": min_ratio}
    }
```

### Fixture-side usage

Two options for how a case references helpers:

**Option α (declarative, recommended):** add a sibling field `L2_validators` to `hard_constraints`:

```jsonc
{
  "id": "CV-AMB-001",
  "hard_constraints": {
    "mesh_object_count": {"minimum": 1}
  },
  "L2_validators": [
    "assert_geometry_exists",
    "assert_reasonable_scale"
  ]
}
```

The loader (in schema or evaluator) expands the named helpers and merges their constraint dicts into `hard_constraints` at load time.

**Option β (imperative):** author pre-expands and embeds the raw primitives directly. Less DRY but no schema change required.

PR-E should pick α — the abstraction gives leverage for future cases and the loader change is small.

## 7. CV-AMB-001 prescription (PR-E's first user)

```jsonc
{
  "id": "CV-AMB-001",
  "hard_constraints": {
    "mesh_object_count": {"minimum": 1}
    // current state — keep
  },
  "L2_validators": [
    "assert_geometry_exists",
    "assert_reasonable_scale"
  ]
}
```

**Notes:**
- `assert_geometry_exists` adds `non_degenerate_mesh_count.minimum=1` on top of the existing `mesh_object_count.minimum=1`. So a 1-mesh flat plane fails L2 (couldn't before).
- `assert_reasonable_scale` defaults: `max_dim=50.0, min_vol=0.001`. Apple-scale objects sit comfortably inside this.
- **Deliberately no `assert_dominant_mesh`** — see §5 (D's "Use sparingly" note). An 8-metaball apple should pass L2; whether it *looks* like an apple is the judge's call.

Expected behavior change: outputs that previously passed L2 by being "any 1 mesh" but were clearly garbage (flat plane, microscopic point) now fail L2 deterministically, sparing judge calls and producing cleaner failure-class signal.

## 8. Implementation hints for PR-E (task #28)

```
Files PR-E will touch:
- nalana_eval/schema.py
    Add Pydantic model for the three new constraint types:
      NonDegenerateMeshCount, SceneBoundingBox, ConceptCarrierExists.
    Add `L2_validators: List[str]` field to TestCaseCard (Option α).
    Add loader logic to expand validator names into hard_constraints
    at TestSuite.from_json_or_dir time (or in TestCaseCard's validator).

- nalana_eval/constraints/standard_validators.py   (new file)
    Three helper functions per §6.
    Registry dict {name -> helper_fn} for loader lookup.

- nalana_eval/evaluator.py
    Add evaluation logic for non_degenerate_mesh_count
    (compute per-mesh BB volume, count non-degenerate),
    scene_bounding_box (compute union BB, check min/max),
    concept_carrier_exists (find max-BB-volume mesh, check ratio).

- tests/test_constraints.py   (new file)
    Per-primitive unit tests with synthetic scenes:
      - 1 cube → passes B, C; passes D with min_ratio=0.5
      - 1 flat plane → fails B; passes C (planes have volume by ε convention)
      - empty scene → fails B, C, D
      - 1 cube at (10000, 10000, 10000) → fails C max_dimension
      - 1 huge cube + 1 tiny sphere → passes D (cube dominates)
      - 5 evenly-sized cubes → fails D with min_ratio=0.5, passes with 0.15

- fixtures/starter_v3/ambiguous.json
    CV-AMB-001 entry: add L2_validators array per §7.

- CHANGELOG.md, docs/handoffs/<date>-pr-e-l2-validators.md
    Standard PR closing artifacts.

Estimated effort: 2-3 hours real coding + 30 min review iteration.
```

## 9. Open questions for PR-E author (Claude or otherwise)

These were discussed but not nailed down — flagged here so PR-E doesn't re-derive:

```
Q1. Should the helper module live at nalana_eval/constraints/
    or directly under nalana_eval/?
→ Lean nalana_eval/constraints/ (new subdirectory) — leaves room for
  future constraint-related modules (e.g., constraint composition
  helpers, drift_check rules). Cost: one new __init__.py.

Q2. Loader expansion timing — in TestSuite.from_json_or_dir,
    or lazily in evaluator?
→ Eager at load time. Makes the resulting TestCaseCard self-contained
  (all constraints visible in one place), simplifies debug/inspection.
  Cost: helper names must resolve at load time; unknown names → error.

Q3. Backward compatibility — what if existing fixtures don't declare
    L2_validators?
→ Treat as empty list (the default). Existing 80 fixtures continue
  to work unchanged. Helpers are pure additions.

Q4. Should assert_geometry_exists be auto-applied to every case (as
    "every case must produce SOMETHING")?
→ No, opt-in. Honors author intent. Some cases (CV-SAF-001 "delete
  all") explicitly want zero meshes — auto-applying would break them.

Q5. Naming bikeshed: assert_* vs require_* vs has_*?
→ assert_* matches Python unittest convention; reads as a precondition
  the model's output must satisfy. Keep.
```

## 10. References

- **ADR-004** (`docs/DECISIONS.md`) — L2/L3 separation; this work strengthens L2 without crossing into L3
- **CLAUDE.md** "Don't break L2 / L3 separation" — operational restatement of ADR-004
- **`docs/handoffs/2026-05-02-15.2-audit-decisions.md`** §10 "CV-AMB-001 edge case" — observed today that the apple case sits in the 1-vs-2 mesh ambiguity window; #15.2 didn't tighten it on purpose, that's PR-E's job
- **Today's mid-session chat** (2026-05-06) — the B/C/D framing emerged in conversation; this doc records the decisions
- **Task #28** — PR-E will implement what this doc designs; this doc is its spec
