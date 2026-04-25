# Multi-Model Evaluation Plan
**Deadline**: 2026-04-29 (next sync)
**Goal**: Run Tier 1–3 prompts through all four models and return scored results.

---

## Models

| Model | Runner Class | Model ID | API Key Env Var |
|---|---|---|---|
| Google Gemini | `GeminiApiRunner` (new) | `gemini-2.5-pro` | `GEMINI_API_KEY` |
| Claude Sonnet | `AnthropicRunner` (new) | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| Claude Opus | `AnthropicRunner` (new) | `claude-opus-4-6` | `ANTHROPIC_API_KEY` |
| GPT-5.4 | `OpenAICompatibleRunner` (new) | `gpt-5.4` | `OPENAI_API_KEY` |

---

## Tier Coverage

| Tier | Difficulty | Current Cases |
|---|---|---|
| Tier 1 | Short | TS-UNIT-001 — Add cylinder |
| Tier 2 | Medium | TS-INT-042 — Bevel cube |
| Tier 3 | Long | TS-E2E-089 — Art Deco lamp |

Each case has 4 voice command variants → **12 prompts per model, 48 API calls total**.

---

## What Needs to Be Built

### 1. Add real API runners — `model_runners.py`
Three new runner classes using `urllib.request` (stdlib only — Blender's Python may not have SDKs):

**`AnthropicRunner`** (shared by Sonnet + Opus, parameterized by model_id)
- POST to `https://api.anthropic.com/v1/messages`
- Headers: `x-api-key`, `anthropic-version: 2023-06-01`
- Body: `{"model": ..., "max_tokens": 2048, "messages": [{"role": "user", "content": prompt}]}`
- Response: `result["content"][0]["text"]`

**`OpenAICompatibleRunner`**
- POST to `https://api.openai.com/v1/chat/completions`
- Headers: `Authorization: Bearer {key}`
- Body: `{"model": ..., "messages": [{"role": "user", "content": prompt}]}`
- Response: `result["choices"][0]["message"]["content"]`

**`GeminiApiRunner`**
- POST to `https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}`
- Body: `{"contents": [{"parts": [{"text": prompt}]}]}`
- Response: `result["candidates"][0]["content"]["parts"][0]["text"]`
- Strip API key from error messages before surfacing

All runners: validate API key at construction (fail-fast with clear error), default to `OutputContract.NORMALIZED`.

### 2. Add multi-model comparison report — `reporting.py`
New method `write_comparison_report(runs: List[BenchmarkRun])` on `BenchmarkReporter`:
- Side-by-side markdown table: rows = metrics, columns = models
- Metrics: `pass@1`, `pass@k`, `execution_success_rate`, `avg_command_accuracy`, `avg_parameter_accuracy`, `avg_sequence_accuracy`, `avg_latency_ms`
- Per-tier sub-tables (Short / Medium / Long)
- Links to each model's individual report
- Output: `results/comparison_{timestamp}.md`

### 3. New evaluation entry point — `run_evaluation.py`
New file alongside `test_run.py`, run via Blender:
```python
# pseudocode
runners = [GeminiApiRunner(...), AnthropicRunner("claude-sonnet-4-6"), 
           AnthropicRunner("claude-opus-4-6"), OpenAICompatibleRunner("gpt-5.4")]
runs = harness.run_models(runners)
reporter.write_comparison_report(runs)
```

---

## Running the Evaluation

```bash
# 1. Export API keys
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GEMINI_API_KEY="AIza..."

# 2. Run smoke test first (no API calls, existing static runners)
blender --background --python testing/benchmark/test_run.py

# 3. Run full evaluation
blender --background --python testing/benchmark/run_evaluation.py
```

---

## Outputs

After a successful run:
- `results/{timestamp}-gemini-2-5-pro/report.md` + `report.json`
- `results/{timestamp}-claude-sonnet-4-6/report.md` + `report.json`
- `results/{timestamp}-claude-opus-4-6/report.md` + `report.json`
- `results/{timestamp}-gpt-5-4/report.md` + `report.json`
- `results/comparison_{timestamp}.md` ← side-by-side scored table

Failed attempts are logged to `artifacts/benchmark_failures.jsonl`.

---

## Task Breakdown (4 People)

Each task is independent — no merge conflicts, all can be worked in parallel.

---

### Task 1 — API Model Runners (`model_runners.py`)
Add three new runner classes to `model_runners.py` using stdlib HTTP only (no third-party SDKs):
- A shared private HTTP helper function for making JSON POST requests
- `AnthropicRunner` — calls the Anthropic Messages API, parameterized by model ID (covers both Sonnet and Opus)
- `GeminiApiRunner` — calls the Gemini generateContent API (replaces the existing static `GeminiRunner` for live runs)
- `OpenAICompatibleRunner` — calls the OpenAI Chat Completions API for GPT-5.4

All runners must: read their API key from an environment variable, raise a clear error at construction if the key is missing, and return the model's raw text response for the harness to normalize.

---

### Task 2 — Multi-Model Comparison Report (`reporting.py`)
Add a `write_comparison_report(runs)` method to the existing `BenchmarkReporter` class:
- Takes the list of `BenchmarkRun` objects (one per model) produced by `harness.run_models()`
- Writes a markdown file to `results/comparison_{timestamp}.md`
- Includes a side-by-side table of all key metrics (pass@1, pass@k, execution success rate, command/parameter/sequence accuracy, avg latency) with one column per model
- Includes a per-tier breakdown table (Short / Medium / Long) using the existing `difficulty_breakdown` data
- Links to each model's individual report at the bottom

---

### Task 3 — Evaluation Entry Point (`run_evaluation.py`)
Create a new file `run_evaluation.py` alongside the existing `test_run.py`:
- Reads all three API keys from environment variables and raises immediately if any are missing
- Instantiates all four runners (Gemini, Sonnet, Opus, GPT-5.4) with the correct model IDs and output contracts
- Creates the harness pointed at `fixtures/sample_cases_v2.json`
- Calls `harness.run_models(runners)` to run all four models sequentially
- Calls `reporter.write_comparison_report(runs)` to write the consolidated output
- Prints all report paths when done
- Runs inside Blender: `blender --background --python testing/benchmark/run_evaluation.py`

---

### Task 4 — Test Fixture Expansion (`fixtures/`)
Expand the current corpus from 3 cases (one per tier) to a richer set for better signal:
- Add 2–3 additional cases per tier (targeting ~9 total cases) covering more `StepKind` variety
- Tier 1 (Short): single-step primitives — translate, scale, rotate, set mode
- Tier 2 (Medium): multi-step edits — inset + extrude, scale + bevel, mode switch + transform
- Tier 3 (Long): multi-object compositions combining creation, editing, and material/camera steps
- Each case needs: `id`, `category`, `difficulty`, 4 `voice_commands`, `initial_scene`, `expected_steps`, `reference_policy`, `quality_signals`
- Validate each new case before committing: `python3 -c "from testing.benchmark.schema import TestSuite; TestSuite.from_json('path/to/fixture.json')"`

---

## Risks

| Risk | Mitigation |
|---|---|
| Models return prose/markdown fences around JSON | Becomes `PARSE_ERROR` in results — visible in failures log. If widespread, add fence-stripping in `_generate()`. |
| Rate limits under burst of 48 sequential calls | Exceptions are caught per-attempt and recorded as non-fatal `runner_error`. No retries needed for first run. |
| `claude-opus-4-6` model ID may not exist (latest is 4.7) | Confirmed by user as intentional. Will surface as HTTP 400 if the ID is wrong. |
| Blender Python missing SDK packages | Solved by using `urllib.request` stdlib only — no third-party packages needed. |
