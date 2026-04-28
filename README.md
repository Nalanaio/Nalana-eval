# Nalana Eval V3.0

> An LLM × Blender 3D modeling evaluation system, built around **constraint validation + preference alignment**.

**中文版本**: [`README.zh.md`](README.zh.md)

---

## What this is, in five minutes

Nalana is a Blender-based 3D modeling product driven by LLMs. The user describes what they want in natural language ("make a red apple"), the LLM emits Blender operations as JSON, and Blender executes those operations to produce a 3D model.

**This evaluation system** answers two questions:

1. **Objective capability**: Which LLM (GPT-5 / Claude / Gemini …) is the best backend for Nalana?
2. **Subjective satisfaction**: Are the model's outputs aesthetically acceptable to users?

**What it is not**: Not the Nalana product itself. It's a **standalone testing tool** — you don't need to launch the full Nalana product to use it.

---

## The whole system in one diagram

```
Test cases you've authored (JSON, 200-300 of them)
        ↓
nalana-eval CLI
   --cases 200 --models gpt-5,claude-sonnet-4-6 --pass-at-k 3
        ↓
For each case:
   1) LLM receives the prompt → emits JSON ops
   2) Blender executes the JSON ops → produces a 3D model
   3) Screenshot (PNG) + scene statistics capture
   4) Three-tier evaluation:
      L1 API unit tests       (deterministic op-by-op comparison)
      L2 constraint validation (hard + topology + soft constraints)
      L3 LLM-as-Judge          (semantics / aesthetics / craftsmanship)
        ↓
Outputs:
   artifacts/run_<timestamp>/
   ├── report.md                ← humans read this
   ├── report.json              ← machines read this
   ├── screenshots/             ← one PNG per attempt
   └── scene_stats/             ← one geometry JSON per attempt

   db/runs.csv                  ← cross-run history aggregate
   db/attempts.csv              ← per-attempt fine-grained data
```

---

## Quick start

### Step 1: install dependencies

```bash
cd /Users/ianian/Nalana-eval
pip install -r requirements.txt

# Install Blender 4.0+ if you don't have it
# macOS: brew install --cask blender
# Linux: download from https://www.blender.org/download/
# Verify: blender --version
```

### Step 2: configure API keys

```bash
# Recommended: write them to .env (already in .gitignore, won't enter git)
cat > .env <<EOF
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
EOF
```

### Step 3: first run (10-case smoke test)

```bash
python -m nalana_eval.cli \
    --cases 10 \
    --models gpt-5 \
    --suite fixtures/starter_v3 \
    --simple-mode      # use simple-mode the first time to confirm the env is OK
```

Output goes to `artifacts/run_<timestamp>/`. Open `report.md` to see results.

### Step 4: real run — 200 cases across multiple models

```bash
python -m nalana_eval.cli \
    --cases 200 \
    --models gpt-5,claude-sonnet-4-6,gemini-2.5-pro \
    --difficulty-dist short:0.4,medium:0.4,long:0.2 \
    --pass-at-k 3 \
    --judge-model gpt-4o \
    --workers 8
```

### Step 5: look at historical trends

```bash
# Last 5 runs of the same model
python -m nalana_eval.cli history --model gpt-5 --last 5

# Multi-model head-to-head
python -m nalana_eval.cli history --compare gpt-5,claude-sonnet-4-6
```

---

## Documentation map

Which doc to read depends on what you want to do:

| What you want to do | Read this | Language |
|---|---|---|
| **Understand the design philosophy and architecture** | [`docs/DESIGN.md`](docs/DESIGN.md) ← **must read** | EN |
| **Learn the CLI** | [`docs/USAGE_GUIDE.md`](docs/USAGE_GUIDE.md) | EN |
| **Author new test cases** | [`docs/TEST_CASE_AUTHORING.md`](docs/TEST_CASE_AUTHORING.md) | 中文 (EN pending — see #11) |
| **Dig into the code-level architecture** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 中文 (EN pending — see #11) |
| **Migrate from the v2.0 system** | [`docs/MIGRATION_FROM_V2.md`](docs/MIGRATION_FROM_V2.md) | 中文 (EN pending — see #11) |
| **Build a calibration set for the LLM judge** | [`calibration/README.md`](calibration/README.md) | 中文 (EN pending — see #11) |
| **Understand the CSV database fields** | [`docs/CSV_SCHEMA.md`](docs/CSV_SCHEMA.md) | 中文 (EN pending — see #11) |

> Chinese originals of `DESIGN.md` and `USAGE_GUIDE.md` are kept alongside as `DESIGN.zh.md` and `USAGE_GUIDE.zh.md`.

---

## Core philosophy (30-second version)

### The problem with the old system

The previous evaluation was built around "reproducing a human designer's Blender operation steps." That doesn't hold up in an AI creative-generation setting — for the same "draw an apple" prompt, a round apple, a cartoon apple, and a photorealistic apple can all be correct.

### The new approach

Replace **"match the answer"** with **"match the constraints"**:

- **Hard constraints** (must be satisfied): how many objects exist, bounding-box ranges, material colors, …
- **Topology constraints** (must be satisfied): manifold-ness, quad ratio, max face count
- **Soft constraints** (scored): weighted continuous metrics like vertex/face count
- **Style intent + LLM judge** (soft signal): does it "look right" / "look good"

We stop asking "did it follow the same steps?" and start asking "does the output match the user's expectation?"

### Three-tier architecture

```
L3 Preference alignment: LLM-as-Judge (shipped) + future DPO
L2 Constraint validation: the main benchmark, scales to 1000+ cases
L1 API unit tests:        repurposed v2.0 cases — regression guard for deterministic ops
```

---

## Repository layout

```
Nalana-eval/
├── README.md                       ← you are here
├── docs/                           ← all documentation
│   ├── DESIGN.md                   ← design philosophy + architecture (the "constitution")
│   ├── USAGE_GUIDE.md              ← detailed CLI usage
│   ├── TEST_CASE_AUTHORING.md      ← test case authoring spec
│   ├── ARCHITECTURE.md             ← code-level architecture
│   ├── MIGRATION_FROM_V2.md        ← migration from v2.0
│   └── CSV_SCHEMA.md               ← database field definitions
│
├── nalana_eval/                    ← main package
│   ├── schema.py                   ← v3.0 data model
│   ├── legacy_schema.py            ← v2.0 (kept for L1 unit tests)
│   ├── contracts.py                ← JSON normalization + safety allowlist
│   ├── dispatcher.py               ← JSON → bpy.ops translator
│   ├── executor.py                 ← Blender-side execution (runs inside worker)
│   ├── scene_capture.py            ← scene statistics capture
│   ├── screenshot.py               ← Workbench-rendered screenshot
│   ├── evaluator.py                ← L2 constraint evaluation
│   ├── judge.py                    ← L3 LLM-as-Judge
│   ├── reporting.py                ← report.md / report.json generation
│   ├── csv_db.py                   ← CSV database read/write
│   ├── runners/                    ← per-provider LLM adapters
│   │   ├── base.py
│   │   ├── openai_runner.py
│   │   ├── anthropic_runner.py
│   │   ├── gemini_runner.py
│   │   └── mock_runner.py
│   ├── workers/                    ← Blender worker execution modes
│   │   ├── pool.py                 ← default worker pool
│   │   ├── worker_loop.py          ← Blender-side script
│   │   └── simple_runner.py        ← --simple-mode entry point
│   ├── history.py                  ← nalana-eval-history implementation
│   ├── review.py                   ← nalana-eval-review implementation
│   └── cli.py                      ← main CLI entry
│
├── prompts/                        ← system prompt configurations
│   ├── eval_default.md             ← default neutral prompt
│   ├── nalana_prod.md              ← Nalana production prompt
│   └── judge_prompt.md             ← judge prompt template
│
├── fixtures/                       ← test cases
│   ├── starter_v3/                 ← v3.0 starter cases (~30)
│   ├── legacy_v2/                  ← v2.0 cases kept for L1 unit tests
│   └── synthetic/                  ← programmatic generator
│       └── generate_cases.py
│
├── calibration/                    ← judge calibration set
│   ├── README.md                   ← calibration handbook
│   ├── reference_images/           ← user-supplied reference images (gitignored)
│   ├── calibrate.py                ← calibration command
│   └── baseline_results/           ← calibration baseline (gitignored)
│
├── db/                             ← database (gitignored)
│   ├── runs.csv                    ← per-run aggregate
│   ├── attempts.csv                ← per-attempt fine-grained
│   ├── judge_vs_human.csv          ← judge-vs-human comparison log
│   └── judge_cache.sqlite          ← judge call cache
│
├── tests/                          ← engineering unit tests (pytest)
│   ├── test_schema.py
│   ├── test_contracts.py
│   ├── test_dispatcher.py
│   ├── test_evaluator.py
│   └── test_judge.py
│
├── artifacts/                      ← per-run outputs (gitignored)
│
├── requirements.txt
├── pyproject.toml
└── .gitignore
```

---

## Where do I look at the CSV database?

`db/runs.csv` and `db/attempts.csv` in your workspace are plain CSV files. Four ways to view them:

1. **Open in Excel / Numbers** — just double-click
2. **`nalana-eval-history` CLI** — produces a comparison table + ASCII trend chart
3. **VS Code / Cursor + a CSV plugin** (e.g. Rainbow CSV)
4. **DuckDB SQL queries**: `duckdb -c "SELECT model_id, AVG(hard_pass_rate) FROM 'db/runs.csv' GROUP BY model_id"`

`db/` being in `.gitignore` only means it stays out of git history — it doesn't affect local browsing.

---

## Relationship to the old (v2.0) system

The old system compared against ground-truth step sequences. The new system validates against constraints. **v2.0 is not deleted** — it becomes the L1 "API unit test suite," guarding against regressions in deterministic operations (delete / undo / default primitives, etc.).

Migration details: [`docs/MIGRATION_FROM_V2.md`](docs/MIGRATION_FROM_V2.md).

---

## Who maintains this

The Nalana engineering team. Issues and PRs welcome.

---

**Suggested next reads: [`docs/DESIGN.md`](docs/DESIGN.md) (why it's designed this way) → [`docs/USAGE_GUIDE.md`](docs/USAGE_GUIDE.md) (how to use it) → [`docs/TEST_CASE_AUTHORING.md`](docs/TEST_CASE_AUTHORING.md) (how to author new cases).**
