# Context bridge: Anthropic Blender plugin research conversation

```yaml
status:        in_progress (this doc) → handed off to new conversation
owner:         ian + Claude Cowork
related_task:  internal #32 (Anthropic plugin research) + #33 (this bridge doc)
related_pr:    (TBD on push — small paper PR)
date_opened:   2026-05-13
date_closed:   —
```

> **This doc bootstraps a separate Cowork conversation** focused on researching
> Anthropic's Blender plugin / integration and extracting actionable lessons
> for Nalana. It is **not** a decisions doc — the new conversation produces
> the decisions; this doc supplies the context to think well.
>
> **For the AI starting the new conversation**: read this end-to-end before
> doing any research. Then follow CLAUDE.md "When you start a new Cowork
> session" 5-step warmup. Research findings get appended to §6 or land in
> a new `docs/RESEARCH/<topic>.md`.

---

## 1. What Nalana is — product vs eval repo

There are **two separate codebases**. Don't conflate them.

### 1.1 Nalana product (the actual thing being built)

**One-line**: a Blender + LLM-driven 3D model generation software.

**Target users**:
- Blender artists who want to skip basic geometry to focus on detailing / art direction.
- Non-Blender specialists in design fields (e.g., Nike shoe designer) who want LLM to produce the rough/basic shape so they can iterate on details and aesthetics. The mental model is: LLM handles "block out the form", human handles "refine".

**Trajectory**: moving toward an **agentic architecture** with explicit stages —
`input analysis → planning → execution → output → RLHF / RLAIF` — each stage
made transparent and individually debuggable. This is the long-arc product
roadmap, not the current state.

**Repo**: private. Lives under `https://github.com/Nalanaio` org. Plus a
product-website repo, also private. Public discovery (e.g. `Nalanaio` org
page) shows only `Nalana-eval`.

### 1.2 Nalana-eval (this repo)

Standalone evaluation system for LLM × Blender capability. Users of the
Nalana product never see this repo — it exists for the dev team to measure
how well candidate LLMs perform on Blender modeling tasks.

It's "**half-precursor**" to the product because many decisions made here
(constraint vocabularies, prompt-engineering patterns, retry strategies)
will inform product implementation when those agentic stages are built.

---

## 2. Nalana-eval V3 architecture (~5 paragraphs)

Three-tier evaluation pipeline:

**L1 — Deterministic regression.** This **IS ground-truth replication.** A
Blender command either runs cleanly with the expected effect or it doesn't —
no creative interpretation involved. L1 covers the "non-creative substrate":
parser correctness, primitive creation, named-object operations, scene-state
preservation invariants. v2 was entirely L1-shaped and that broke when we
tried to extend it to creative work; V3 keeps L1 strictly for what L1 is
actually good at.

**L2 — Constraint validation.** Schema-driven, deterministic given a fixture
+ scene snapshot. The fixture declares **hard_constraints** (`mesh_object_count`,
`bounding_boxes`, `required_named_objects`, etc.) and the evaluator computes
binary pass/fail against the final scene. This is where most cases live.
**L2 expresses "is this a plausible candidate answer?"** — it sets floors,
not ceilings. Creative variation (an LLM-authored chair using 5 meshes
instead of 2) passes L2 as long as the floor is met.

**L3 — LLM-as-judge.** Probabilistic soft signal. Asked: "given the prompt,
the reference style intent, and a screenshot of the output, how well does
this satisfy the intent?" Returns a 0-1 score per dimension (e.g.,
recognizability, aesthetic coherence, spatial coherence) plus a brief
reason. **L3 expresses "is this the right answer?"** — ceilings.

**Critical separation rule (ADR-004)**: L3 judge scores **never** feed back
into L2 pass/fail logic, retry triggers, or aggregate scoring. If a retry
loop needs feedback, it uses L2 constraint failure reasons, not judge
output. This separation lets us calibrate L3 independently and prevents
soft-signal noise from corrupting hard-signal metrics.

**Test case schema** (`nalana_eval/schema.py`, locked 2026-05-06 in
#15.1 + #15.2): each case has four classification axes —
**SceneComplexity** (single_object / multi_object / composition / full_scene),
**Provenance** (handcrafted / synthetic / llm_authored),
**Tag** (canonical / adversarial / ambiguous / honeypot),
**draft** (bool, for in-progress LLM-authored cases). Plus the runtime
fields `prompt_variants`, `initial_scene`, `hard_constraints`,
`soft_constraints`, `topology_policy`, `style_intent`, `judge_policy`,
`artifact_policy`.

---

## 3. Current technical philosophy (this week's consensus)

```
P1. Context engineering > model quality.
    "Maximize squeezing existing models via harness + context engineering
    before resorting to expensive fine-tuning." Current providers:
    Claude (Anthropic), GPT-5 / o-series (OpenAI), Gemini (Google).
    All high-end commercial. Future: may move to OSS (Gemma, Qwen);
    designs should not assume native function-calling / structured output
    is always present (graceful degradation).

P2. Schema-driven constraints over ground-truth replication —
    BUT ONLY AT L2 AND L3. L1 is ground truth because L1 work is
    deterministic and creative interpretation doesn't apply. Don't
    apply v3 schema philosophy retroactively to L1.

P3. L2 = floor, L3 = ceiling.
    L2 catches "did the model produce something plausible?" — lower
    bounds, never upper bounds (upper bounds kill creative latitude).
    L3 evaluates "is it a good answer?" — soft signal, decoupled
    from L2.

P4. Retry-with-feedback for fault tolerance (ADR-004).
    Default OFF. Opt-in via --retry-with-feedback flag. When enabled,
    a failed attempt's next iteration receives a structured
    summary of L2 constraint failures (NOT judge output, per ADR-004).
    Rationale: data showed ~7.5% rescue rate on real models;
    not robust enough to justify breaking single-shot semantics
    by default.

P5. Strict separation of concerns in PRs (ADR-003).
    One PR = one concern. Bundling mixed concerns blocks attribution.
    This applies to research products too: an Anthropic plugin study
    that suggests three changes to Nalana → three separate PRs.

P6. Authoring vs evaluation separation (locked today, 2026-05-13).
    LLM authoring CLI (#15.3) outputs candidate cases; the existing
    benchmark evaluates them. Don't bake reachability checks into
    authoring — let #15.6 human review + #15.4 drift checker + first-run
    benchmark stats handle quality signal. Authoring is a producer;
    the rest is the consumer/filter chain.
```

---

## 4. #15 epic status as of 2026-05-13

`#15` ≡ "Test case authoring pipeline" epic. Sub-issues `#15.1`-`#15.12`
on GitHub project board. (Internal task tracker `#13` is the same thing,
historical artifact — see CLAUDE.md "Issue / task numbering convention".)

```
✓ #15.1   Schema fields (SceneComplexity / Provenance / Tag / draft)
          + 80-fixture mechanical backfill
          [merged 2026-05-06]

✓ #15.2   Existing-fixture audit per ADR-005 strict mode
          9 cases re-classified, CV-CMP-003 judge_policy: audit_only → score,
          5 cases acceptable_styles expanded, --difficulty-dist deprecated
          [merged 2026-05-06]

⏳ #15.3  LLM authoring CLI ← next main-line, decisions Q1-Q5 locked 2026-05-13
   Q1 ✓ paper-first
   Q2 → CLI args (default) + --config YAML (batch); no wizard
   Q3 → fixtures/llm_authored_v3/<id>.json with draft: true (no staging dir)
   Q4 → native structured output (Anthropic tools / OpenAI json_schema / Gemini response_schema)
        + strict Pydantic + retry-with-feedback (max 1 retry) + .author_failures.jsonl
   Q5 → no inline benchmark; --smoke-test flag (opt-in, mock_runner) as schema-level
        sanity backstop; quality signal goes to #15.4 / #15.6 / first-run stats

⏳ #15.4  Drift checker — cross-validates scene_complexity vs constraint shape
         (e.g., tagged COMPOSITION but mesh_object_count.minimum < 2 → warn)

⏳ #15.5  Honeypot infrastructure — deliberately-failing cases mixed into
         runs to detect judge malfunction

⏳ #15.6  Human spot-check / draft review pipeline — flip draft: true → false
         after human approves the LLM-authored case

⏳ #15.7  through #15.12 — outstanding sub-issues, scope crystallizes once
         #15.3-#15.6 land
```

Sibling cleanup-track work (not blocking #15):
- ⏳ `PR-D` (task #27): attempts.csv schema migration helper. Independent.
- ⏳ `PR-E` (task #28): L2 validator vocabulary implementation +
  CV-AMB-001 tightening. Spec ready at
  `docs/handoffs/2026-05-06-l2-validator-vocabulary.md`.

---

## 5. Why this research now — Anthropic plugin's relevance

Anthropic released a Blender integration / plugin (precise form TBD —
official plugin, MCP server, computer-use demo, or all three). The
demo videos look impressive. We have **near-zero direct experience**
with it but **substantial overlap of problem space**:

- Both products: connect an LLM to Blender to produce / edit 3D models.
- Both products: must constrain LLM output to executable Blender operations.
- Both products: care about precision (the model has to do exactly what was
  asked) AND creative latitude (the model needs space to produce
  something visually good).

Anthropic almost certainly faced — and made decisions about — many of the
same questions Nalana is currently facing:
- LLM ↔ Blender interface shape (Python exec? bpy operator subset?
  high-level DSL?)
- Multi-turn state management (does the LLM see the current scene?
  how is it serialized?)
- Error recovery (what happens when an LLM emits an invalid operation?)
- User-facing UX vs developer-facing abstraction

Studying their answers gives us **cheap reconnaissance** before we commit
expensive design choices in `#15.3` and beyond.

---

## 6. Research questions

> ⚠ The user has only watched demo videos. Don't assume the AI in the
> research conversation already knows what the plugin is. Start by
> figuring out what exactly exists, then dig into specifics.

### 6.1 Foundational (figure these out first)

```
F1. What exactly exists?
    - Is there an "official Anthropic Blender plugin"? Or is what we saw a
      computer-use demo? A community MCP server? Multiple things?
    - Where to find: anthropic.com / docs.anthropic.com / GitHub anthropics/* /
      blog posts / partner announcements.
    - Distinguish: official product vs demo vs marketing video vs
      community work.

F2. What does it do at the user-facing level?
    - Modeling? Editing? Rendering? Animation? Texturing? Subset?
    - Conversational vs single-shot?
    - Inside Blender (as a panel) or external (as a chat that drives Blender)?
```

### 6.2 Technical (the meat — once F1/F2 are answered)

```
T1. LLM ↔ Blender interface.
    - Function calling / tool use schema? (List specific tool names + their
      argument schemas.)
    - Raw Python execution via bpy?
    - A higher-level DSL (e.g., command list with safe verbs)?
    - Pre-translation layer (Anthropic translates natural language → DSL →
      Python in stages)?

T2. State / scene representation.
    - What does the LLM see between turns? Snapshot of scene tree? Rendered
      screenshot? Both? Symbolic + visual?
    - Is the scene serialized into the prompt every turn (expensive but
      simple) or maintained out-of-band (cheap but error-prone)?
    - Object naming conventions, hierarchies, modifiers — how represented?

T3. Error handling / retry.
    - What happens when the LLM emits invalid Python or a tool call that
      fails? Auto-retry with error message? User mediation? Silent skip?
    - Are there guardrails — e.g., refuse to delete unconfirmed, prevent
      runaway loops, undo capability?
    - How is "the model is stuck" detected and handled?

T4. Prompting / context.
    - Is there a visible system prompt / instructions? Reverse-engineer or
      find leaks/disclosure.
    - How is the user's natural-language intent broken down before reaching
      Blender? (Mentioned in §1.1: Nalana plans agentic stages —
      input-analysis / planning / execution / output. Does Anthropic's
      plugin do anything analogous?)
    - Few-shot examples in the prompt? Reference style guides?

T5. Safety / sandboxing.
    - Can the LLM access arbitrary Python (filesystem, network)? Or only
      a curated bpy subset?
    - Is the user shown the operation before it executes?

T6. Multi-step / planning.
    - Can the model plan a sequence and execute? Or one-step-at-a-time
      reactive?
    - Does it backtrack when a step fails?
```

### 6.3 Product (positioning insights for Nalana product)

```
P1. Who is the user?
    - Skill level — Blender power user, hobbyist, complete novice?
    - Industry — game dev, architecture, product design, art, education?
    - Are they paying customers, demo viewers, or beta testers?

P2. Where does it fit in the Blender workflow?
    - Replace traditional modeling? Augment? Side-by-side alternative?
    - Used at start of project (block-out) or throughout?

P3. Differentiation vs traditional CAD / parametric tools.
    - Anthropic positions it as ___? (Quote marketing copy.)
    - What's the conversational model's edge over parametric / scripted
      authoring (Geometry Nodes, Grasshopper, Houdini)?

P4. Pricing / business model.
    - Free addon? Paid? Bundled with Claude subscription?
    - Per-model? Per-render? Compute-metered?

P5. Reception — what do users say?
    - Reddit r/blender, Twitter, Hacker News, YouTube comments.
    - Most common praise (= our reference for "what works").
    - Most common complaints (= our anti-pattern reference).

P6. Comparable products.
    - Are there Blender competitors (Cline / Cursor / Copilot for Blender)?
    - Other CAD-AI tools (Spatial AI, Vizcom, Krea)?
    - How does Anthropic's plugin position vs them?
```

---

## 7. Expected deliverables back to Nalana (research output)

The research conversation should produce **at minimum**:

1. **A new doc**: `docs/RESEARCH/2026-05-XX-anthropic-blender-findings.md`
   (or similar). Same handoff template structure. Covers what was found
   for each F / T / P question, with citations (links to docs, videos,
   blog posts).

2. **A "Nalana implications" section** at end of that doc with two
   subsections:
   - **Technical implications** — list of specific design changes
     suggested for `#15.3` LLM authoring CLI, plus possibly `#15.6`
     review pipeline. Each item should be concrete enough to become
     a GitHub issue.
   - **Product implications** — list of positioning / differentiation
     observations relevant to the Nalana product. Less concrete (no
     PRs to file in this repo), but feeds into product strategy
     conversation later.

3. **One or more new tasks** in the TodoList for actions surfaced:
   - "Update #15.3 paper-first design with Anthropic insight on X" — if
     applicable.
   - "Investigate Y prompt-engineering pattern they use" — if applicable.
   - "Add Z honeypot category inspired by their failure modes" — if
     applicable to #15.5.

4. **NO code changes** in the research conversation. Findings are paper.
   Actionable PRs are filed but not implemented in that conversation —
   per ADR-003 single concern, "research" and "implement based on
   research" are different concerns and live in separate sessions.

---

## 8. Working agreement for the new conversation

```
Startup (per CLAUDE.md "When you start a new Cowork session"):
  1. Read CLAUDE.md cover-to-cover (~190 lines, 1-2 min)
  2. Read this doc end-to-end
  3. Skim docs/SYSTEM_MAP.md §1-2 for the layered architecture
  4. Optional: glance at docs/DECISIONS.md ADR-004 (L2/L3 separation)
     and ADR-005 (taxonomy) — they're the relevant invariants
  5. TaskList check — should see tasks #32 (this work) + #33 (this doc) +
     #34 (#15.3 paper, blocked on this completing) in flight
  6. Confirm focus with ian: "Loading context from CLAUDE.md and the
     2026-05-13 Anthropic bridge doc. Today: research Anthropic Blender
     plugin per the F/T/P questions in §6. Proceed?"

Conduct:
  - When in doubt about a Nalana invariant, prefer this doc + SYSTEM_MAP
    over speculation. If neither answers, ask ian.
  - Don't reopen Q1-Q5 decisions on #15.3 — they're locked. If Anthropic
    research surfaces evidence the lock is wrong, flag explicitly and
    let ian re-decide.
  - Cite all external sources (URLs preferred). Anthropic-side artifacts
    may move; capture quotes / screenshots if a primary source might
    disappear.
  - Don't fetch random URLs without anchoring — start from anthropic.com,
    docs.anthropic.com, github.com/anthropics, and demo video URLs ian
    provides.

Closing:
  - Update this doc's status YAML and section §7 with what shipped.
  - Add a CHANGELOG entry under the new doc.
  - Per ADR-003: if findings warrant code action, open new issues/PRs,
    don't write code in the research session.
```

---

## 9. Glossary / acronym dump

For the new conversation's quick reference (no need to ask):

- **L1 / L2 / L3** — the three evaluation tiers. See §2.
- **ADR-NNN** — Architecture Decision Records in `docs/DECISIONS.md`.
  - ADR-001/002: V3.0 baseline (constraint-based eval).
  - ADR-003: one PR = one concern.
  - ADR-004: retry-with-feedback default OFF; L2/L3 separation.
  - ADR-005: TaskLength dropped, SceneComplexity added, L3 judge for spatial
    coherence.
- **#15 series** — test-case-authoring epic. Internal numbering used to be
  `#13.x`; renamed to `#15.x` 2026-05-06 to align with GitHub epic issue
  number. CLAUDE.md "Issue / task numbering convention" has the mapping.
- **PR-A / PR-C / PR-F / PR-G / PR-H / PR-I** — cleanup-track PRs without
  GitHub sub-issue numbers. Letter shorthand only.
- **Fixture** — a single test case JSON in `fixtures/starter_v3/` or
  `fixtures/synthetic/` or (eventually) `fixtures/llm_authored_v3/`.
- **Corpus** — the 80 existing fixtures: 30 starter_v3 + 50 synthetic.
- **Provenance** — taxonomy axis: `handcrafted` / `synthetic` /
  `llm_authored`.
- **bpy** — Blender's Python API.
- **MCP** — Model Context Protocol; Anthropic's open standard for
  connecting LLMs to external tools.

---

## 10. References

- **CLAUDE.md** — AI onboarding (mandatory read on session start)
- **docs/SYSTEM_MAP.md** — 4-module architecture; what files do what
- **docs/DECISIONS.md** — ADRs, especially ADR-004 + ADR-005
- **docs/handoffs/2026-05-02-15.2-audit-decisions.md** — the existing-
  fixture audit decisions (#15.2's source of truth)
- **docs/handoffs/2026-05-06-l2-validator-vocabulary.md** — L2 validator
  vocabulary paper, the spec PR-E will implement
- **docs/handoffs/2026-05-06-15.2-audit.md** — #15.2 PR's handoff doc
- **CHANGELOG.md** — last 5-8 entries cover the past week's work
- **TaskList** — current in-flight + queue
- **GitHub Nalanaio org** — `https://github.com/Nalanaio` — `Nalana-eval`
  is the only public repo; product repos are private
