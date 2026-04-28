# Nalana Eval V3.0 — Design Document

**Version**: 3.0
**Date**: 2026-04-25
**Author**: Nalana eval & testing team
**Status**: Active (supersedes the legacy PDF "Model Performance Evaluation Standards Framework Proposal")

---

## 0. Who this document is for

This document is the "constitution" of the new Nalana evaluation system. If you are:

- **A user of the eval system** (developer, QA): read sections 1, 2, 6, 7, then jump to `USAGE_GUIDE.md`
- **A test case author** (product, designer, QA): read sections 3 and 4, then jump to `TEST_CASE_AUTHORING.md`
- **An architecture maintainer** (Nalana engineering): read it end to end, with focus on sections 5, 8, 9
- **A first-time reader**: start from section 1 ("Why a rewrite"). Each section is laid out as "what / why / how"

**Important prerequisites**: this document assumes you know what Blender, Python, and JSON are. It does not assume you know LLM evaluation, 3D mesh topology, or DPO. Those concepts are explained **the first time they appear**.

---

## 1. Why a rewrite

### 1.1 Background

Nalana is a Blender + LLM 3D modeling product — the user describes what they want in natural language ("draw a red apple"), the LLM emits Blender operations as JSON, and Blender executes them to produce a 3D model.

The previous evaluation system (see the legacy PDF "Model Performance Evaluation Standards Framework Proposal") was built around the idea of **"ground truth as baseline"** — a human designer hand-builds the same object in Blender, that recording becomes the "correct answer," and the LLM is judged on how closely its operation sequence and result "reproduce" that ground truth.

### 1.2 Why the old system isn't enough

The old system assumes "for the same product, there's only one correct answer." That's true in traditional software engineering (input A always equals output B), but **it does not hold in AI creative-generation**:

- "Draw an apple" can mean round, blocky, cartoon, photorealistic — any of these may be what the user wants
- "Make a chair" can be four-legged, three-legged, armchair, office chair — completely different topology paths
- Even "create a cube" — the LLM might use `bpy.ops.mesh.primitive_cube_add()`, or build a face and extrude it (`extrude`). Both are correct.

Two more fatal problems with the old system:

1. **Not scalable**. Every ground truth requires a human to manually build the object in Blender and record the operation sequence. Adding 100 test cases takes ~200 person-hours.
2. **Suppresses true LLM capability**. Forcing the LLM to "reproduce" human operations means forcing it to abandon its own optimal solution. GPT-5 might have a smarter topology path, but because it doesn't match ground truth, it gets failed.

### 1.3 Core idea of the new system

Replace **"match the answer"** with **"match the constraints"**. Don't ask "are the operation steps the same as a human's?" — ask "does the output 3D model satisfy the necessary constraints?":

- **Hard constraints**: object count and types, material color, bounding-box size, relative positions — must be satisfied; failing any one fails the case.
- **Topology constraints**: manifold-ness, quad ratio, max face count — measures "industrial-grade mesh quality."
- **Soft constraints**: continuous metrics like vertex/face count, weighted score. **Does not decide pass/fail**, only contributes to score.
- **Style intent + LLM judge**: when the user's intent involves semantic dimensions like "does it look like X" / "is it pretty," an LLM judge soft-scores it according to the author-declared style.

This mechanism preserves "objective, machine-evaluable" properties (you can run 1000 cases fully automatically) while accepting the "answers aren't unique" nature of 3D creation.

### 1.4 Is the old system completely abandoned?

**No**. Some operations have a **single correct answer** — for example "undo" can only be `bpy.ops.ed.undo()`, "switch to edit mode" can only be `bpy.ops.object.mode_set(mode='EDIT')`. For these **deterministic operations**, step-by-step comparison is still the most precise testing method.

The new system **demotes rather than deletes**: v2.0 step comparison is demoted to the **"L1 API unit test suite,"** covering ~50–100 deterministic cases as a regression red line (see section 2.1). The v3.0 constraint test is the main benchmark.

---

## 2. The three-tier evaluation architecture

The new system is bottom-up in three layers. Each layer has independent goals, case sets, and metrics, and they don't interfere with each other:

```
┌─────────────────────────────────────────────────────────┐
│  L3: Preference Alignment — long-term work              │
│  · LLM-as-Judge semantic review (shipped)               │
│  · Implicit feedback (keep/delete/edit) → DPO data (TBD) │
│  · Human Elo rankings (cold-start phase)                │
├─────────────────────────────────────────────────────────┤
│  L2: Constraint-Based Evaluation — main benchmark       │
│  · Hard constraints: scene state, object props, materials │
│  · Topology: manifold, quad ratio, face count cap       │
│  · Soft constraints: weighted continuous metrics        │
│  · Scales to 1000+ cases, < 10 minutes per run          │
├─────────────────────────────────────────────────────────┤
│  L1: API Correctness (Deterministic Unit Tests)         │
│  · v2.0 legacy fixtures repurposed into 50-100 cases    │
│  · Step comparison + Execution Success                  │
│  · Pass-to-Pass red line                                │
└─────────────────────────────────────────────────────────┘
```

### 2.1 L1: API correctness (preserved with limited scope)

**Goal**: prevent regressions in "basic API calls" after a model update.

**Scope**: only **deterministic operations** — cases where both the parameters and the operation type have a unique correct answer.

**Case count**: 50–100 (no need for more; this layer is regression protection, not capability evaluation).

**TaskFamily limits**:

| TaskFamily | Example prompt | Unique correct answer |
|---|---|---|
| `scene_hygiene_safety` | "Delete all objects" | `bpy.ops.object.select_all() + bpy.ops.object.delete()` |
| `primitive_creation_default` | "Add a default cube" | `bpy.ops.mesh.primitive_cube_add()` with no parameters |
| `camera_assignment` | "Set camera to position (1, 2, 3)" | parameters come directly from the user instruction |
| `mode_switching` | "Enter edit mode" | `bpy.ops.object.mode_set(mode='EDIT')` |

**Key metrics**:

- **Execution Success Rate**: does the generated JSON execute in Blender without errors
- **Command Accuracy**: is the operation type correct (e.g., `ADD_MESH` right, `SET_MATERIAL` wrong)
- **Parameter Accuracy**: given correct operation type, are parameters within 5% tolerance
- **Pass-to-Pass**: cases that previously passed **must still pass** after a model update — red line, no regressions allowed

### 2.2 L2: Constraint validation (core, scalable)

**Goal**: verify the LLM can produce "acceptable" 3D output, without constraining the operation path.

**Scope**: all non-deterministic tasks — i.e., tasks with "creative latitude."

**Case count**: starts at 200–300 (handcrafted + programmatically extended), targets 500–1000.

**Case schema overview** (full details in `TEST_CASE_AUTHORING.md`):

```json
{
  "id": "CV-OBJ-042",
  "category": "Object Creation",
  "difficulty": "Medium",
  "task_family": "parameterized_primitive_creation",
  "prompt_variants": [
    "Create a red sphere, radius about 2 meters",
    "Add a roughly 2 m radius red ball",
    "创建一个红色的球体，半径大约 2 米"
  ],
  "initial_scene": { "mode": "OBJECT" },
  "hard_constraints": {
    "mesh_object_count": { "minimum": 1 },
    "required_object_types": ["MESH"],
    "bounding_boxes": [
      { "target": "__scene__", "size_range": { "minimum": [3, 3, 3], "maximum": [5, 5, 5] }}
    ],
    "materials": [
      { "target": "*", "base_color": [1.0, 0.0, 0.0, 1.0], "tolerance": 0.2 }
    ]
  },
  "topology_policy": {
    "manifold_required": true,
    "quad_ratio_min": 0.0,
    "max_vertex_count": 10000
  },
  "soft_constraints": [
    { "name": "reasonable sphere vertex count", "metric": "total_vertices", "direction": "min", "target": 100, "weight": 0.5 }
  ],
  "style_intent": {
    "explicit": false,
    "concept": "sphere",
    "concept_aliases": ["ball", "球"],
    "acceptable_styles": ["geometric"]
  },
  "judge_policy": "score",
  "artifact_policy": {
    "require_screenshot": true,
    "write_scene_stats": true
  }
}
```

**Key design principles:**

1. **Multiple prompt variants**: each case must have 3–5 `prompt_variants` to test robustness to different phrasings
2. **Constraints describe the result, not the process**: wrong = "use `primitive_uv_sphere_add`"; right = "the scene contains a mesh whose bounding box falls within [3,3,3]–[5,5,5]"
3. **Constraints should be as loose as possible**: only exclude clear errors, don't covertly specify a single answer. A 2 m sphere should accept bbox [3,3,3]–[5,5,5], not [3.99,3.99,3.99]–[4.01,4.01,4.01]
4. **Topology constraints are tiered by use case**:

| Use case | manifold | quad_ratio_min | Note |
|---|---|---|---|
| Concept / preview | false | 0.0 | Nalana's current default |
| Game / real-time render | true | 0.7 | Standard game-mesh requirement |
| Film / VFX | true | 0.85 | Industrial grade, subdivisible |
| 3D printing | true | 0.0 | Must be watertight, but tris are fine |

### 2.3 L3: Preference alignment

**Goal**: evaluate "matches user aesthetic / expectation" — this layer cannot be captured by pure geometric constraints.

**Currently shipped sub-module: LLM-as-Judge** (see section 4).

**Future phases**:

- Phase B: human Elo ranking (10–20 art reviewers do pairwise rankings of multiple outputs for the same prompt)
- Phase C: implicit-feedback DPO (instrument the product to collect keep/delete/edit signals, build `(prompt, chosen, rejected)` triples for training)

L3's specific design is in sections 4 and 9.

---

## 3. Glossary of key terms

To avoid team-communication drift, all eval-related discussions use this unified terminology:

| Term | Definition |
|---|---|
| **Test case** | One JSON entry describing the input prompt, initial scene, constraints, style intent, etc. |
| **Suite** | A collection of cases (e.g. `starter_v3.json`) |
| **Run** | A complete execution of the eval system, producing one run folder |
| **Attempt** | One model call + one Blender execution + one scoring for a given case. Pass@k means k attempts per case |
| **Hard constraint** | A constraint that decides pass/fail. Failing any one fails the entire case |
| **Topology constraint** | Geometric quality requirements (manifold, quad ratio, face count). Also decides pass/fail |
| **Soft constraint** | A weighted, scored continuous metric. **Does not decide pass/fail**, only contributes to score |
| **Style intent** | Author-declared user-expected style (cartoon / realistic / low-poly / …), used to guide the LLM judge |
| **Judge** | The LLM-as-Judge module — a multimodal LLM that views the screenshot and gives soft scores |
| **Pass@k** | k attempts per case; if at least one passes, the case is considered passed |
| **Pass-to-Pass** | Cases that previously passed **must still pass** under a new model version (red-line metric) |
| **Failure class** | Failure cause categorization: PARSE_ERROR / EXECUTION_ERROR / CONSTRAINT_FAILED / TOPOLOGY_FAILED / SAFETY_BLOCKED, etc. |
| **JSON dispatcher** | The eval system's JSON parser, translates LLM-emitted JSON into actual `bpy.ops.*` calls |
| **Worker pool** | Multiple long-running Blender processes processing cases in parallel |
| **Run folder** | The output directory of a single run (contains report.md / report.json / screenshots / scene_stats) |
| **CSV database** | Cross-run persistent structured database (runs.csv + attempts.csv) |
| **Calibration set** | A collection of reference images of known quality, used to detect systematic bias in the LLM judge |
| **Honeypot** | A deliberately failing case mixed into a run to detect judge malfunction |

---

## 4. LLM-as-Judge: intent-aware semantic review

### 4.1 Why we need it

Constraint validation (L2) covers "API competence" and "basic geometric common sense," but has two blind spots:

1. **Concept matching**: the user says "draw an apple," the model produces a manifold sphere that satisfies all constraints — but **it doesn't look like an apple**: no stem, no bottom indent
2. **Aesthetics**: two chairs both satisfy constraints — one well-proportioned, one badly proportioned. Constraints can't tell them apart.

L3's LLM-as-Judge covers these blind spots.

### 4.2 The core challenge: pick the wrong yardstick and you'll wrongly fail good work

LLM judges have training preferences. GPT-4o has seen mostly photorealistic "professional 3D apples," so by default it **judges cartoon work by photorealistic standards** — meaning cartoon apples will always get low scores in its eyes.

The new evaluation system uses a **four-step mechanism** to ensure the judge is "style-neutral":

### 4.3 The four-step mechanism in detail

#### Step 1: case author explicitly declares `style_intent`

```json
"style_intent": {
  "explicit": true,            // did the user explicitly specify a style
  "style": "cartoon",          // required if explicit=true
  "concept": "apple",          // the object concept
  "concept_aliases": ["fruit"],// accepted concept aliases
  "acceptable_styles": ["cartoon", "stylized"]  // if explicit=false, list all acceptable styles
}
```

**Meaning**: the case author moves "user intent" from an LLM guess to an explicit contract in the schema. The judge no longer has to guess — it just executes the declaration.

#### Step 2: two-step prompt enforcing "detect first, then evaluate"

The judge prompt structure (full version in `prompts/judge_prompt.md`):

```
You are a 3D modeling reviewer.

[User's original instruction]
"draw an apple"

[Case author's intent declaration]
- explicit: false
- concept: apple
- acceptable_styles: [cartoon, realistic, low-poly, stylized]

[You must score in the following steps]

Step 1 (detect): observe the rendered image and identify the modeler's intent:
   - detected_style: cartoon / realistic / low-poly / stylized / abstract
   - detected_concept: what concept does this object represent?

Step 2 (verify alignment):
   - if explicit=true, compare detected_style to the user-specified style; mismatch → style_alignment_pass=false
   - if explicit=false, detected_style is valid if it's in acceptable_styles
   - concept check: detected_concept must be in [concept] ∪ concept_aliases

Step 3 (score by detected_style's own standard):
   ⚠️ Critical rule: score by the standard of the detected style itself, not by cross-style comparison
   - judging cartoon → standard is "cuteness, exaggeration, clear edges that cartoon modeling should have"
   - judging realistic → standard is "detail, proportions, materials that realistic modeling should have"
   - judging low-poly → standard is "the geometric facetedness, consistent face count of low-poly"
   Don't deduct points from cartoon for "not being realistic"; don't deduct from low-poly for "lacking detail."

Return strict JSON (schema below).
```

**Return schema**:

```json
{
  "detected_style": "cartoon",
  "detected_concept": "apple",
  "style_alignment_pass": true,
  "concept_alignment_pass": true,
  "scores_within_detected_style": {
    "concept_recognizability": 4,    // 1-5, can you tell it's an apple
    "style_execution": 3,            // 1-5, how well it's done as a cartoon apple
    "geometric_quality": 3           // 1-5, topology, proportions, completeness
  },
  "judged_under_standard": "cartoon",  // ⚠️ mandatory declaration of the yardstick used, for audit
  "reasoning": "...",                  // brief justification
  "confidence": 0.8                    // 0-1, judge's confidence in its own score
}
```

#### Step 3: calibration set verifies the judge has no systematic bias

**Procedure**:

1. Prepare 20–30 screenshots of "known-good cartoon modeling" + 20–30 of "known-good realistic modeling"
2. Have the judge score them with the prompt above
3. **Expected**: cartoon group's average under cartoon standard ≈ realistic group's average under realistic standard (within ±0.3)
4. If the two groups have systematic bias (e.g., cartoon is always 1 point lower), the prompt needs adjustment, or switch the judge model

See `calibration/README.md`.

#### Step 4: variance check + soft-signal wrapping + honeypots

- For each case, have the judge **score 3 times** (temperature=0.3, slight randomness to test stability)
- Take the **median** for the report, record `judge_stddev`
- If `judge_stddev > 1.0` (5-point scale), separately flag "judge unstable" and prompt human review
- Judge scores **never participate in hard pass/fail** — they are soft signals only, weighted at no more than 30% of the total score
- Insert 1 honeypot every 10 cases (a deliberately-failing case: empty scene, object unrelated to prompt). If the judge gives a honeypot ≥ 4, mark the entire run `judge_unreliable`

### 4.4 Configurable judge model

CLI flag `--judge-model`:

| Default | GPT-4o (multimodal stable, JSON-mode reliable, $0.01/judgment) |
|---|---|
| Alternatives | Claude Sonnet 4.6, Gemini 2.5 Pro |
| Dual-judge mode | `--judge-model gpt-4o,claude-sonnet-4` — two independent scores averaged, 2× cost, further bias reduction |

**Key constraint**: model comparisons must use the same judge, otherwise it's not fair.

### 4.5 Cost and limits

- Single judge call ≈ $0.01 (GPT-4o), 200 cases × 3 scorings = ~$6/run
- CLI `--judge-budget 5.0` is a hard cap; on overrun, remaining calls are skipped and N/A is recorded
- Cache: `hash(prompt + screenshot_pixels) → judge_result`, 30-day TTL, saves 30–50% of cost

---

## 5. Execution architecture

### 5.1 End-to-end data flow

```
┌─────────────────┐
│  Test Suite     │  fixtures/starter_v3/*.json
│  (JSON cases)   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  CLI (nalana-eval)                      │
│  parse --cases / --models / --pass-at-k │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Harness (main scheduler)               │
│  · load suite                           │
│  · sample by difficulty/length          │
│  · dispatch to ModelRunner + WorkerPool │
└────────┬────────────────────────────────┘
         │
         ├──→ ┌─────────────────┐
         │    │  ModelRunner    │  call external LLM API
         │    │  (OpenAI/etc.)  │  return JSON ops
         │    └────────┬────────┘
         │             │
         │             ▼
         │    ┌─────────────────┐
         │    │  JSON normalize │  contracts.py
         │    │  + safety allow │  reject dangerous ops
         │    └────────┬────────┘
         │             │
         ▼             ▼
┌─────────────────────────────────────────┐
│  WorkerPool (default) or SimpleRunner   │
│  · send case JSON to Blender worker     │
│  · subprocess + stdin/stdout protocol   │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Blender Worker (worker_loop.py)        │
│  · runs inside Blender                  │
│  · reset_scene → execute ops → snapshot │
│  · render PNG screenshot (Workbench)    │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Evaluator (constraint evaluation)      │
│  · hard constraints → pass/fail         │
│  · topology → pass/fail                 │
│  · soft constraints → weighted score    │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Judge (LLM-as-Judge)                   │
│  · receives prompt + screenshot + intent │
│  · two-step scoring → soft signal       │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Reporter                               │
│  ├── report.md / report.json            │
│  ├── screenshots/ + scene_stats/        │
│  └── write db/runs.csv + db/attempts.csv │
└─────────────────────────────────────────┘
```

### 5.2 Execution modes: Worker Pool (default) vs Simple Mode

#### Worker Pool mode (default, throughput-first)

At startup, spawn N long-lived `blender --background --python worker_loop.py` processes. `worker_loop.py` enters a loop: read case JSON line by line from stdin, write the result to stdout after each case. The harness uses `subprocess.Popen` to manage N pipes, and resets scenes between cases via `bpy.ops.wm.read_factory_settings(use_empty=True)`.

- ✅ 1000 cases in 5–10 minutes
- ⚠️ Processes can grow in memory or hang. Auto-restart workers every 100 cases (health check)
- Default N = `cpu_count() * 0.75`, configurable via `--workers`

#### Simple Mode (CLI: `--simple-mode`)

For each case, the harness launches a fresh `blender --background --python single_run.py -- input.json output.json screenshot.png`. Blender exits when done, the next case restarts.

- ✅ Absolutely clean environment, a hang doesn't affect the next case
- ❌ 1000 cases in 30–50 minutes
- Suitable for CI, debug, first-time validation

### 5.3 LLM calls bypass XML-RPC

**Important architectural decision**: the eval system **does not reuse** Nalana production's XML-RPC (port 8765).

**Why**:
- The production RPC methods are things like `enqueue_op_safe`, not "accept prompt, return JSON"
- The eval system must support arbitrary third-party LLMs (GPT-5 / Claude / Gemini); these can't all be wrapped as Blender plugins
- Decoupling LLM calls from Blender execution lets the eval system run independently — no need to launch the full Nalana product first

**Approach**:
- The eval system's `ModelRunner` calls external APIs directly (OpenAI SDK / Anthropic SDK / google.genai)
- Once it has the JSON, it sends it to a Blender worker via subprocess (stdin/stdout, not RPC)
- Inside the Blender worker, the eval system's own dispatcher (`nalana_eval.dispatcher`) parses the JSON and executes

### 5.4 Screenshot rendering

**Authoritative choice**: Workbench engine + procedural isometric camera + 800×600 PNG.

**Why this stack:**

| Choice | Alternative | Why we don't use it |
|---|---|---|
| Workbench engine | EEVEE / Cycles | EEVEE needs lighting setup, 3-5 sec/frame; Cycles is 5-30 sec/frame — 1000 cases can't afford it |
| `bpy.ops.render.render(write_still=True)` | `bpy.ops.screen.screenshot()` | screenshot completely fails in `--background` mode |
| Procedural isometric camera | Reuse the scene's existing camera | Test scenes don't always have a camera; even if they do, it may not point at the generated object |
| 800×600 PNG | 1920×1080 | For evaluation, rough shape/material is enough — saves time and disk. Configurable via CLI flag |

**Core code** (implemented in `nalana_eval/screenshot.py`):

```python
def render_scene_to_png(output_path, resolution=(800, 600)):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = resolution[0]
    scene.render.resolution_y = resolution[1]
    scene.render.filepath = output_path
    scene.render.image_settings.file_format = 'PNG'

    # Procedural camera placement: bbox center + isometric angle, distance = max_dim × 2.5
    # (Full implementation in nalana_eval/screenshot.py)
    place_camera_iso(scene)
    bpy.ops.render.render(write_still=True)
```

Each attempt produces **two images**: original (800×600) + thumbnail (512×384, for markdown embedding).

---

## 6. CLI and usage

### 6.1 Main entry: `nalana-eval`

Full usage in `USAGE_GUIDE.md`. The most common invocation:

```bash
# Run 200 cases comparing GPT-5 and Claude Sonnet 4.6
nalana-eval \
    --cases 200 \
    --models gpt-5,claude-sonnet-4-6 \
    --difficulty-dist short:0.4,medium:0.4,long:0.2 \
    --pass-at-k 3 \
    --judge-model gpt-4o \
    --suite fixtures/starter_v3 \
    --workers 8

# Output: artifacts/run_<timestamp>/
```

**API key handling**:
- Read from environment variables (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`)
- Also supports `--api-keys-file path/to/secrets.env`
- Never accepted as plain command-line args (would leak into shell history)

### 6.2 Auxiliary CLIs

| Tool | Purpose |
|---|---|
| `nalana-eval-history` | Query `db/*.csv`, output trend / comparison tables |
| `nalana-eval-review` | Collect HUMAN_REVIEW_BLOCK from report.md, write back to attempts.csv |
| `nalana-eval-calibrate` | Run the judge calibration set, output a baseline report |

---

## 7. Output artifacts

### 7.1 Single run-folder structure

```
artifacts/run_20260425_143022_<run_id_8>/
├── report.md                        ← human-readable main report
├── report.json                      ← full structured data
├── failures.jsonl                   ← per-failure detailed log (one line each)
├── screenshots/
│   ├── CV-OBJ-042_attempt_0.png         ← original 800×600
│   ├── CV-OBJ-042_attempt_0_thumb.png   ← thumbnail 512×384 (for md embed)
│   ├── CV-OBJ-042_attempt_1.png
│   └── ...
├── scene_stats/
│   ├── CV-OBJ-042_attempt_0.json    ← bmesh stats, bbox, object list
│   └── ...
├── prompts_used.json                ← which system prompt this run used
├── config.json                      ← all CLI args used in this run
└── baseline_delta.json              ← comparison to previous run of same model (if any)
```

### 7.2 Cross-run persistence: CSV database

`db/runs.csv` — one row per run (multi-model comparison = N rows). Full field definitions:

| Column | Description |
|---|---|
| run_id, timestamp_utc, model_id, prompt_template_version | identifiers |
| total_cases, total_attempts, difficulty_dist (JSON), category_dist (JSON) | input structure of this run |
| execution_success_rate, hard_pass_rate, topology_pass_rate, avg_soft_score, pass_at_1, pass_at_3 | L1/L2 main metrics |
| avg_judge_semantic, avg_judge_aesthetic, avg_judge_professional, judge_reliable | L3 soft signals + judge health |
| avg_latency_ms, total_cost_usd | cost |
| report_md_path, report_json_path, git_commit, notes | index + audit |

`db/attempts.csv` — one row per attempt per case. Full fields in `docs/CSV_SCHEMA.md`.

`db/judge_vs_human.csv` — long-running accumulation of "judge vs human" disagreements, used in the future to fine-tune the judge prompt.

### 7.3 Markdown report style

Approximate structure of `report.md`:

```markdown
# Nalana Benchmark Run Report
**Run ID**: run_20260425_143022
**Models**: gpt-5, claude-sonnet-4-6
**Total Cases**: 200 | **Total Attempts**: 600 (Pass@3)

## Executive Summary
| Model | Hard Pass Rate | Topology Pass | Avg Soft | Pass@3 | Judge Avg |
|---|---|---|---|---|---|
| gpt-5 | 0.78 | 0.85 | 0.72 | 0.91 | 3.8/5 |
| claude-sonnet-4-6 | 0.74 | 0.83 | 0.69 | 0.88 | 3.9/5 |

## Breakdown by Category / Difficulty / Length
... (tables)

## Top Failure Reasons
1. CONSTRAINT_FAILED (23): bounding_box too small ...
2. TOPOLOGY_FAILED (12): non-manifold edges ...

## Sample Cases (failing + boundary cases)

### ❌ FAIL: CV-OBJ-042 — "Create a red sphere"
[![attempt 0](screenshots/CV-OBJ-042_attempt_0_thumb.png)](screenshots/CV-OBJ-042_attempt_0.png)

**Hard constraints**: ✗ material color (got grey, expected red)
**Topology**: ✓ manifold, quad_ratio = 0.0 (allowed)
**Judge** (under "geometric" standard): semantic=4 / style=3 / quality=3 / stddev=0.3

<!-- HUMAN_REVIEW_BLOCK:CV-OBJ-042:attempt_0
override: pending
corrected_semantic:
corrected_aesthetic:
corrected_professional:
reviewer:
note:
END_HUMAN_REVIEW_BLOCK -->
```

A reviewer edits the `HUMAN_REVIEW_BLOCK` comment block in their editor (note: HTML comments, not rendered), then runs `nalana-eval-review --collect path/to/report.md` to flow feedback back into the `judge_human_override` column of `db/attempts.csv`.

---

## 8. Metrics

### 8.1 L1 metrics (API unit tests)

| Metric | Formula | Red line |
|---|---|---|
| Execution Success Rate | successful execs / total cases | ≥ 95% |
| Command Accuracy | correct op types / total ops | ≥ 90% |
| Parameter Accuracy | matching params / total ops (given correct op type) | ≥ 85% |
| **Pass-to-Pass Rate** | post-update passes among previously-passing cases / previously-passing cases | **= 100% (red line)** |

### 8.2 L2 metrics (constraint validation)

| Metric | Formula | Current target |
|---|---|---|
| Hard Pass Rate | cases passing all hard constraints / total | ≥ 70% |
| Topology Pass Rate | cases passing topology / total | ≥ 80% |
| Avg Soft Score | mean of weighted soft-constraint scores | ≥ 0.6 |
| Pass@1 | cases passing on attempt 0 / total | ≥ 60% |
| Pass@3 | cases with at least one pass in 3 attempts / total | ≥ 85% |

### 8.3 L3 metrics (preference alignment)

| Metric | Formula | Current target |
|---|---|---|
| Judge Semantic Avg | mean of judge semantic scores (5-pt scale) | ≥ 3.5 |
| Judge Aesthetic Avg | mean of judge aesthetic scores | ≥ 3.0 |
| Judge Professional Avg | mean of judge craftsmanship scores | ≥ 3.0 |
| Judge Stability | 1 − fraction of cases with stddev > 1.0 | ≥ 0.9 |
| Judge Honeypot Catch Rate | fraction of honeypots scored ≤ 2 | ≥ 0.95 |
| Calibration Drift | judge bias on calibration set (see calibration/) | ≤ 0.3 |

### 8.4 Model comparison baseline

We retain the legacy "Gemini Pro 3 as baseline" idea but change it to: the **most recent GPT-5 run** as a moving baseline. Each new model run automatically diffs against the most recent baseline run, output in `baseline_delta.json`.

**Red-line rules** (model cannot ship if):
- Pass-to-Pass Rate < 100%
- Execution Success Rate drop > 2%
- Hard Pass Rate drop > 5%
- Topology Pass Rate drop > 5%

### 8.5 Engineering-level deterministic tests (don't conflate with model benchmark)

The eval system's **own** unit / integration tests live in `tests/` and don't appear in benchmark reports:

- `test_schema.py`: v3.0 schema validation
- `test_contracts.py`: JSON normalization, allowlist, parameter bounds
- `test_dispatcher.py`: correctness of JSON → bpy.ops translation
- `test_evaluator.py`: constraint computation correctness
- `test_judge.py`: judge prompt construction, JSON parsing
- `test_csv_db.py`: CSV write/read, human-review writeback

These run with pytest, decoupled from the `nalana-eval` benchmark.

---

## 9. Preference-alignment roadmap

### Phase 1: now (shipped with V3.0)

✅ LLM-as-Judge (intent-aware, four-step, calibration set)
✅ Honeypots
✅ Judge cache + budget cap
✅ Human-review feedback channel (HUMAN_REVIEW_BLOCK → CSV)
✅ Long-running judge_vs_human.csv accumulation

### Phase 2: human Elo ranking (suggested 2–4 weeks out)

Recruit 10–20 art reviewers; each does pairwise rankings of 3 different models' outputs for the same prompt. 50 prompts × 5 judgments = 250 data points is enough to establish an initial Elo baseline.

Tool: `nalana-eval-elo` (Phase 2 implementation)

### Phase 3: implicit-feedback collection (depends on product-side instrumentation)

Embed in the Nalana Blender plugin:
- `kept` / `deleted` / `edited` / `final_selected` signals
- `time_to_first_edit` / `edit_distance`
- final selection when there are multiple candidates

Data collection → store in `db/preference_events.csv` → export as DPO training data.

### Phase 4: DPO training (needs 2000+ preference pairs)

Build `(prompt, chosen, rejected)` triples:
- chosen = `final_selected: true` or `kept: true && edit_distance < threshold`
- rejected = `deleted: true` or `edit_distance > threshold`
- Exclude data with unclear attribution (e.g., 5-second consecutive deletion of all candidates)

First-round DPO → A/B test old vs new model → iterate.

---

## 10. Mapping from the legacy PDF system

| Legacy PDF concept | New system equivalent | Change |
|---|---|---|
| Ground-truth sequence | L1 legacy fixtures (deterministic ops only) | Scope drastically narrowed, kept for regression only |
| Command Accuracy | L1 metric (deterministic only) | Kept but L1-only |
| Parameter Accuracy | L1 metric | Same |
| Geometric Accuracy (Chamfer Distance) | L1 only when reference mesh is available | L2 doesn't use it at all |
| Execution Success | Baseline gate at every layer | Upgraded |
| Quad Ratio / Manifold | L2 TopologyPolicy | Upgraded from quality_signals to formal constraint |
| Multimodal Reasoning Score | L2 screenshot + L3 LLM-as-Judge | Split |
| Productions Accepted Rate | L3 Phase 3 implicit feedback (future) | Roadmap |
| Resolution Rate (SWE-bench) | L2 Hard Pass Rate | Concept aligned, implementation rewritten |
| Pass@k | L2 Pass@k via prompt_variants over multiple attempts | Kept |
| Pass-to-Pass | L1 red line | Kept |

---

## 11. FAQ

**Q: Can I still use old v2.0 fixtures?**
Yes. The `--legacy-suite` flag points at a v2.0 fixture file to run L1 unit tests. But the default benchmark no longer uses them.

**Q: If a prompt is highly ambiguous ("make something nice"), how do I write the constraints?**
Keep only the most basic hard constraints (`mesh_object_count >= 1`, `manifold_required: false`) and hand assessment to the LLM-as-Judge.

**Q: How do I set soft-constraint weights?**
Start with all weights = 1.0 (equal). As Elo data accumulates, back-derive optimal weights — if artists prefer high quad ratio, raise its weight.

**Q: The judge gave me an unfair score, what do I do?**
In `report.md`'s `HUMAN_REVIEW_BLOCK`, fill in the override fields and run `nalana-eval-review --collect`. Over time `judge_vs_human.csv` accumulates and feeds back into judge-prompt fine-tuning.

**Q: Is Chamfer Distance gone entirely?**
Only kept for L1 deterministic cases that have an explicit reference mesh. L2 doesn't use it at all.

**Q: Can I skip LLM-as-Judge?**
Yes. Add `--no-judge` to skip L3 entirely. But for formal benchmarks we recommend leaving it on, since constraints can't capture semantics.

**Q: What system prompt is used when comparing models?**
By default all models use the same `eval_default.md` (for fair comparison). To compare "with vs without Nalana business prompt," use `--system-prompt nalana-prod`.

**Q: Can 1000 cases really finish in 10 minutes?**
Depends on hardware. With 8 workers, Workbench rendering, and ~3 ops/case average, ~5–8 minutes. More CPU cores → faster.

---

## Appendix A: Dependencies and environment

- Python 3.10+
- Blender 4.0+ (`blender` in PATH, or specify via `BLENDER_BIN` env var)
- pip dependencies in `requirements.txt` (pydantic, openai, anthropic, google-genai, Pillow)
- OS: macOS / Linux / Windows (tested on macOS)

## Appendix B: Contributor guide

Adding new cases → `fixtures/starter_v3/<category>.json`. When opening a PR, run `pytest tests/test_schema.py` to confirm schema validation passes.

Adding a new task family → simultaneously update the `TaskFamily` enum in `nalana_eval/schema.py`, the template table in `TEST_CASE_AUTHORING.md`, and the contract description in `prompts/eval_default.md`.

Changing the judge prompt → must rerun the calibration set and compare to baseline drift.

---

**End of document. For full usage details see `USAGE_GUIDE.md`; for case authoring details see `TEST_CASE_AUTHORING.md`.**
