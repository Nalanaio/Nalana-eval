# Nalana Eval — CLI Usage Guide

> This document teaches you **how to use** the system. If you want to understand **why it's designed this way**, read `DESIGN.md` first.

---

## Table of contents

- [Prerequisites: environment setup](#prerequisites-environment-setup)
- [Common commands quick reference](#common-commands-quick-reference)
- [Main command: `nalana-eval`](#main-command-nalana-eval)
- [Auxiliary command: `nalana-eval-history`](#auxiliary-command-nalana-eval-history)
- [Auxiliary command: `nalana-eval-review`](#auxiliary-command-nalana-eval-review)
- [Auxiliary command: `nalana-eval-calibrate`](#auxiliary-command-nalana-eval-calibrate)
- [What a run folder looks like](#what-a-run-folder-looks-like)
- [How to read report.md](#how-to-read-reportmd)
- [Common usage scenarios](#common-usage-scenarios)
- [Common troubleshooting](#common-troubleshooting)

---

## Prerequisites: environment setup

### 1. Python dependencies

```bash
cd /Users/ianian/Nalana-eval
python -m venv .venv         # virtual env recommended
source .venv/bin/activate    # Linux/macOS
pip install -r requirements.txt
```

### 2. Blender 4.0+

The eval system needs to invoke Blender externally to run cases:

```bash
# macOS
brew install --cask blender

# Linux (Ubuntu/Debian)
sudo snap install blender --classic

# Or download from the official site: https://www.blender.org/download/
```

**Verify**:

```bash
blender --version    # should print Blender 4.x.x
```

If `blender` isn't in PATH, set the environment variable:

```bash
export BLENDER_BIN=/Applications/Blender.app/Contents/MacOS/Blender   # macOS example
```

### 3. API key configuration

**Recommended**: write to `.env` (at the repo root) — the system loads it automatically.

```bash
cat > .env <<EOF
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
EOF
```

**Security reminder**: `.env` is in `.gitignore` and won't enter git. **Never** put API keys directly on the command line — they end up in shell history.

If you only want to test some models, configure only those keys (missing ones get skipped and marked `model_unavailable` in the report).

---

## Common commands quick reference

```bash
# Smoke test (10 cases, fastest env validation)
python -m nalana_eval.cli --cases 10 --models gpt-5 --simple-mode

# Main benchmark (200 cases, multi-model comparison)
python -m nalana_eval.cli \
    --cases 200 --models gpt-5,claude-sonnet-4-6,gemini-2.5-pro \
    --pass-at-k 3 --workers 8

# Run the L1 legacy unit-test suite (regression guard)
python -m nalana_eval.cli --legacy-suite fixtures/legacy_v2/sample_cases_v2.json --models gpt-5

# View historical trends
python -m nalana_eval.cli history --model gpt-5 --last 10

# Multi-model comparison table
python -m nalana_eval.cli history --compare gpt-5,claude-sonnet-4-6

# Collect human review feedback
python -m nalana_eval.cli review --collect artifacts/run_<id>/report.md

# Run the judge calibration set
python -m nalana_eval.cli calibrate --judge-model gpt-4o
```

> **Note**: all subcommands are invoked via `python -m nalana_eval.cli <subcommand>`. If you've installed the setuptools entry points, you can use `nalana-eval ...`, `nalana-eval-history ...`, etc. directly.

---

## Main command: `nalana-eval`

### Full parameter table

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--cases N` | int | all | how many cases to run (sampled by distribution) |
| `--models M1,M2,...` | str | gpt-5 | LLMs to test, comma-separated (run sequentially) |
| `--suite path` | str | fixtures/starter_v3 | test case directory or file |
| `--legacy-suite path` | str | none | run L1 legacy unit-test suite (v2.0 format) |
| `--difficulty-dist` | str | uniform | difficulty distribution, e.g. `short:0.3,medium:0.5,long:0.2` |
| `--pass-at-k k` | int | 3 | k attempts per case |
| `--workers N` | int | cpu_count*0.75 | number of Blender workers |
| `--simple-mode` | flag | off | fall back to per-case subprocess mode (slow but stable) |
| `--judge-model M` | str | gpt-4o | LLM-as-Judge model |
| `--judge-budget USD` | float | 10.0 | judge call budget cap (USD) |
| `--no-judge` | flag | off | disable LLM-as-Judge entirely |
| `--system-prompt name` | str | eval-default | system prompt: `eval-default` or `nalana-prod` |
| `--temperature T` | float | 0.7 | LLM sampling temperature |
| `--seed N` | int | 42 | random seed (for reproducibility) |
| `--output-dir path` | str | artifacts/ | run-folder output location |
| `--api-keys-file path` | str | .env | API key file |
| `--verbose` | flag | off | verbose logging |

### Parameter detail

#### `--cases` and distribution parameters

```bash
# 200 cases, sampled by difficulty distribution
--cases 200 --difficulty-dist short:0.4,medium:0.4,long:0.2
# Actually runs: 80 short + 80 medium + 40 long
```

If a distribution bucket is short on cases in the suite, the system borrows from other buckets (and emits a warning in the report).

#### `--models` multi-model behavior

Comma-separated model names, run **sequentially** (not concurrently), reasons:
1. Same-vendor API rate limits aren't shared across models
2. Different vendors could run in parallel, but mixed logs are hard to debug
3. Sequential time is bounded (200 cases × 3 models ≈ 30 minutes)

Each model produces its own run folder. `db/runs.csv` gets N rows (one per model), but they share the same `run_group_id`.

#### `--pass-at-k`

`k=1`: 1 attempt per case. Fastest, but doesn't capture LLM randomness.
`k=3` (**default**): 3 attempts per case. SWE-bench industry standard.
`k=5`: more stable pass-rate estimate, 5× cost.

Each attempt uses a different prompt variant (if the case has multiple `prompt_variants`), and rotates the temperature seed.

#### `--workers` and execution mode

| Mode | 1000-case time | Use case |
|---|---|---|
| Worker pool (default) | 5–10 min | Day-to-day formal benchmarks |
| `--simple-mode` | 30–50 min | CI, debug, first-time validation |

Worker pool spawns N long-lived `blender --background` processes, with `read_factory_settings(use_empty=True)` resetting the scene between cases. Workers auto-restart every 100 cases (memory-leak guard).

#### `--judge-model` and `--judge-budget`

```bash
# Single judge (default)
--judge-model gpt-4o

# Dual-judge averaged (lower bias, 2× cost)
--judge-model gpt-4o,claude-sonnet-4-6
```

When the budget is exceeded, remaining judge calls are skipped, marked `judge skipped: budget exceeded` in the report.

#### `--system-prompt`

| Value | Prompt used | What it tests |
|---|---|---|
| `eval-default` (default) | neutral prompt at `prompts/eval_default.md` | **bare-LLM capability under fair-test conditions** |
| `nalana-prod` | `prompts/nalana_prod.md` (mirror of production) | **end-to-end performance with the Nalana business prompt added** |

When comparing models, you **must** use the same system prompt — otherwise it's not fair.

---

## Auxiliary command: `nalana-eval-history`

Reads `db/runs.csv` + `db/attempts.csv`, outputs trend / comparison.

### Usage

```bash
# Single-model trend over last N runs
python -m nalana_eval.cli history --model gpt-5 --last 10
# Outputs ASCII line chart + key-metrics table

# Multi-model head-to-head
python -m nalana_eval.cli history --compare gpt-5,claude-sonnet-4-6 --metric hard_pass_rate

# Single-case history
python -m nalana_eval.cli history --case CV-OBJ-042 --model gpt-5

# Output CSV / JSON
python -m nalana_eval.cli history --model gpt-5 --last 10 --format json > trend.json

# PNG trend chart (needs matplotlib)
python -m nalana_eval.cli history --model gpt-5 --last 10 --plot trend.png
```

---

## Auxiliary command: `nalana-eval-review`

Collects `HUMAN_REVIEW_BLOCK` entries from `report.md` and writes them back to the `judge_human_override` columns of `db/attempts.csv`.

### Workflow

1. Run a benchmark, open `artifacts/run_<id>/report.md`
2. In your browser/editor, look at each case's screenshot + judge score
3. **Think the judge got it wrong?** Edit that case's `<!-- HUMAN_REVIEW_BLOCK -->`:

   ```markdown
   <!-- HUMAN_REVIEW_BLOCK:CV-OBJ-042:attempt_0
   override: disagree           ← change to agree / disagree / partial
   corrected_semantic: 5        ← the score you think is correct (5-pt scale)
   corrected_aesthetic: 4
   corrected_professional: 3
   reviewer: ian                ← your name
   note: judge didn't recognize this as cartoon style    ← any explanation
   END_HUMAN_REVIEW_BLOCK -->
   ```

4. Run the collector:

   ```bash
   python -m nalana_eval.cli review --collect artifacts/run_<id>/report.md
   ```

   The system parses all review blocks and writes back to the corresponding rows of `db/attempts.csv` (`judge_human_override`, etc.), simultaneously appending to `db/judge_vs_human.csv` for long-term learning data.

5. Multiple reviewers on the same run: each runs `--collect` after their pass. Later writes override earlier ones (same case + reviewer is unique), but all reviewer records are kept.

### Batch review

```bash
# Collect from multiple runs
python -m nalana_eval.cli review --collect-glob 'artifacts/run_*/report.md'

# Show only pending review items (override: pending)
python -m nalana_eval.cli review --pending --run <run_id>
```

---

## Auxiliary command: `nalana-eval-calibrate`

Runs the judge calibration set to detect systematic bias in the LLM judge. See `calibration/README.md` for details.

### Quick calibration

```bash
# Run all calibration sets (cartoon + realistic + low-poly, 20-30 each)
python -m nalana_eval.cli calibrate --judge-model gpt-4o

# Run a single style only
python -m nalana_eval.cli calibrate --judge-model gpt-4o --style cartoon
```

Output goes to `calibration/baseline_results/<judge_model>_<timestamp>.json`, containing:
- mean + stddev for each style
- cross-style bias analysis (the gap between cartoon group's mean under cartoon standard and realistic group's mean under realistic standard)
- recommendations (if drift > 0.3, switch judge model or adjust prompt)

---

## What a run folder looks like

Each `nalana-eval` invocation produces an independent folder:

```
artifacts/run_20260425_143022_<run_id_8>/
├── report.md                        ← human-readable main report (your daily driver)
├── report.json                      ← full structured data
├── failures.jsonl                   ← per-failure detailed log (debugging)
├── config.json                      ← all CLI args used in this run
├── prompts_used.json                ← which system prompt this run used
├── baseline_delta.json              ← comparison to last run of the same model
│
├── screenshots/
│   ├── CV-OBJ-042_attempt_0.png         ← original 800×600
│   ├── CV-OBJ-042_attempt_0_thumb.png   ← thumbnail 512×384
│   ├── CV-OBJ-042_attempt_1.png
│   ├── CV-OBJ-042_attempt_1_thumb.png
│   └── ...
│
└── scene_stats/
    ├── CV-OBJ-042_attempt_0.json    ← bmesh stats, bbox, object list, materials
    └── ...
```

**Why does each attempt get an original + thumbnail?**

- Original (800×600): high-resolution, for human reviewers to see detail
- Thumbnail (512×384): embedded in markdown, fast to load

`report.md` references the thumbnail by relative path; clicking jumps to the original:

```markdown
[![attempt 0](screenshots/CV-OBJ-042_attempt_0_thumb.png)](screenshots/CV-OBJ-042_attempt_0.png)
```

The whole run folder **can be packaged and sent to anyone** — images won't go missing because all paths are relative.

---

## How to read report.md

Standard `report.md` structure:

### 1. Executive Summary (top)

A single comparison table:

```markdown
| Model | Hard Pass | Topology Pass | Avg Soft | Pass@3 | Judge Avg | Cost |
|---|---|---|---|---|---|---|
| gpt-5 | 78% | 85% | 0.72 | 91% | 3.8/5 | $4.21 |
| claude-sonnet-4-6 | 74% | 83% | 0.69 | 88% | 3.9/5 | $5.10 |
```

### 2. Distribution (input structure)

What this run actually ran:

```markdown
**Categories**: Object Creation: 80, Transformations: 50, Materials: 40, Compositional: 30
**Difficulty**: Short: 80, Medium: 80, Long: 40
```

### 3. Breakdown (by dimension)

Pass rate per category / difficulty / task_family — to find the model's weak spots.

### 4. Top Failure Reasons

Aggregated by `failure_class` — where the model fails most:

```markdown
1. CONSTRAINT_FAILED (23 cases)
   - 18 × bounding_box too small
   - 5  × material color mismatch
2. TOPOLOGY_FAILED (12 cases)
   - 12 × non-manifold edges
3. PARSE_ERROR (3 cases)
   - 3  × invalid JSON
```

### 5. Sample Cases

Selected **representative** failing and boundary cases — each one displays its thumbnail, constraint result, judge score, and `HUMAN_REVIEW_BLOCK`.

### 6. Baseline Delta

Diff from last run of the same model (positive = improvement, negative = regression):

```markdown
| Metric | This run | Last run | Delta |
|---|---|---|---|
| Hard Pass Rate | 78% | 76% | +2.0% ↑ |
| Pass@3 | 91% | 92% | -1.0% ↓ |
```

### 7. Judge Reliability

Judge health metrics: were honeypots given high scores? Was variance high?

```markdown
- Honeypots correctly low-scored: 9/10 (90%) ✓
- Cases with judge_stddev > 1.0: 3 (1.5%) ✓
- Calibration drift since last run: +0.05 (within ±0.3 threshold) ✓
```

---

## Common usage scenarios

### Scenario A: daily smoke test (5 minutes)

5 minutes every morning to verify the main model hasn't regressed:

```bash
python -m nalana_eval.cli \
    --cases 30 --models gpt-5 --pass-at-k 1 --workers 4
```

Just look at `report.md`'s Executive Summary.

### Scenario B: pre-release formal benchmark (30–60 minutes)

A complete run before a model goes to production:

```bash
python -m nalana_eval.cli \
    --cases 300 --models gpt-5 --pass-at-k 5 \
    --workers 8 --judge-model gpt-4o,claude-sonnet-4-6
```

Red lines: Pass-to-Pass = 100%, Hard Pass Rate must not drop more than 5% from previous version.

### Scenario C: model selection experiment (2–3 hours)

Deciding which LLM to use as Nalana's backend:

```bash
# 200 cases × 3 models × pass@3 = 1800 attempts
python -m nalana_eval.cli \
    --cases 200 \
    --models gpt-5,claude-sonnet-4-6,gemini-2.5-pro,gpt-4o \
    --pass-at-k 3 --workers 8
```

Then use `nalana-eval-history --compare gpt-5,claude-sonnet-4-6` for head-to-head comparison.

### Scenario D: pinning down a regression (troubleshooting)

A run suddenly drops 10% in pass rate —

```bash
# 1. Check baseline_delta.json to confirm it's really a regression
cat artifacts/run_<id>/baseline_delta.json

# 2. Check failures.jsonl to find which cases dropped
jq '.failure_class' artifacts/run_<id>/failures.jsonl | sort | uniq -c

# 3. Re-run the failing batch with detailed inspection
python -m nalana_eval.cli \
    --cases-from artifacts/run_<id>/failures.jsonl \
    --models gpt-5 --pass-at-k 1 --simple-mode --verbose
```

### Scenario E: debugging a specific case's judge score

```bash
# Isolate a single case, crank judge variance to 5 runs
python -m nalana_eval.cli \
    --case-ids CV-OBJ-042 \
    --models gpt-5 \
    --judge-runs 5 \
    --simple-mode --verbose
```

---

## Common troubleshooting

### Error: `blender: command not found`

Set the `BLENDER_BIN` env var:

```bash
# macOS
export BLENDER_BIN=/Applications/Blender.app/Contents/MacOS/Blender

# Linux
export BLENDER_BIN=/snap/bin/blender
```

Or install blender to PATH.

### Error: `OPENAI_API_KEY not set`

Check that `.env` is in cwd (the repo root). Or specify it explicitly:

```bash
python -m nalana_eval.cli ... --api-keys-file /path/to/.env
```

### Blender worker hangs / case times out

Usually a worker memory leak or a case triggering a Blender bug. Workarounds:

1. Reduce workers: `--workers 4`
2. Switch to simple mode: `--simple-mode`
3. Find the trigger case in `failures.jsonl` and run it in isolation

### Judge gave an unfair score

Use the `nalana-eval-review` flow: edit `HUMAN_REVIEW_BLOCK` in report.md and run `--collect`.

If judge bias is **global** (not just one case), run the calibration set:

```bash
python -m nalana_eval.cli calibrate --judge-model gpt-4o
```

If calibration drift > 0.3, consider switching judge model or adjusting the prompt (`prompts/judge_prompt.md`).

### CSVs are getting large after many runs

```bash
# Check size
ls -lh db/

# Archive data older than 90 days
python -m nalana_eval.cli db archive --before 2026-01-01

# Or copy and clear
cp db/runs.csv db/runs_archive_2026Q1.csv
echo "" > db/runs.csv  # dangerous! back up first
```

Or migrate to SQLite (see end of `docs/CSV_SCHEMA.md`).

---

## Next steps

- Want to author new cases → [`TEST_CASE_AUTHORING.md`](TEST_CASE_AUTHORING.md)
- Want to understand the code-level architecture → [`ARCHITECTURE.md`](ARCHITECTURE.md)
- Want to modify the judge prompt → [`../prompts/judge_prompt.md`](../prompts/judge_prompt.md) + run the calibration set to verify
- Hit a bug / want a new feature → open an issue or PR
