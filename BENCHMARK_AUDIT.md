# Nalana Benchmark Audit

This memo summarizes the current benchmark and test-case mechanism in `testing/benchmark/` after the dual-contract upgrade, and compares it with the production command path in `nalana_core/commands/` and `addon/command_exec.py`.

Relevant implementation files:

- `testing/benchmark/schema.py`
- `testing/benchmark/contracts.py`
- `testing/benchmark/executor.py`
- `testing/benchmark/metrics_evaluator.py`
- `testing/benchmark/model_runners.py`
- `testing/benchmark/reporting.py`
- `testing/benchmark/test_harness.py`
- `testing/benchmark/synthetic_ground_truth.py`
- `testing/benchmark/fixtures/sample_cases_v2.json`
- `nalana_core/commands/schema.py`
- `nalana_core/commands/safety.py`
- `addon/command_exec.py`

## When and Where It Runs

This benchmark is a separate evaluation harness for Nalana's **execution stage**. It is not running every time a user uses Nalana in an ordinary interactive Blender session.

For normal end-user use, Nalana still follows the live path through voice capture, transcription, command generation, XML-RPC, and Blender-side execution. The benchmark skips that live workflow and instead runs offline for developer and QA evaluation against curated benchmark fixtures.

The current implementation must run in Blender's Python runtime because the executor imports and uses `bpy` and `bmesh` directly. It needs real Blender access to:

- reset scenes
- reconstruct `initial_scene`
- execute canonical, typed, or legacy-safe commands
- capture actual mesh/object snapshots
- compute geometry metrics such as quad ratio, manifold, and Chamfer distance

Typical usage is a repeatable headless Blender invocation, for example:

```bash
blender --background --python testing/benchmark/test_run.py
```

`test_run.py` is the smoke-test entrypoint, while `test_harness.py` is the reusable suite orchestrator.

At a high level, the benchmark loop is:

1. Load a fixture suite.
2. Build a reference scene from `expected_steps`.
3. Invoke a model/backend for a benchmark attempt.
4. Execute the candidate output through the safe benchmark executor.
5. Snapshot the resulting Blender scene.
6. Score command, parameter, sequence, geometry, and latency metrics.
7. Write Markdown/JSON reports and baseline comparisons.

## Current Architecture

The benchmark is now split into distinct layers:

- `schema.py`
  Defines the versioned fixture format, canonical `NormalizedStep`-based case structure, runtime artifacts, run summaries, and benchmark result models.

- `contracts.py`
  Defines the benchmark-safe canonical step catalog, validates step arguments, normalizes model outputs, and compiles canonical steps into:
  - legacy Blender-op payloads
  - typed production commands

- `executor.py`
  Owns scene reset, deterministic reference generation, fail-closed execution, scene quotas/timeouts, and scene snapshot capture.

- `metrics_evaluator.py`
  Computes command accuracy, parameter accuracy, sequence accuracy, quad ratio, manifold, Chamfer distance, and `Pass@k`.

- `model_runners.py`
  Defines the benchmark-facing model runner abstraction plus static, callable, XML-RPC, and Gemini baseline runners.

- `reporting.py`
  Persists baseline snapshots, writes Markdown and JSON reports, and computes summary and delta views.

- `synthetic_ground_truth.py`
  Validates LLM-authored synthetic cases by compiling them, building references, and either accepting or quarantining them.

- `test_harness.py`
  Orchestrates the full benchmark flow across suite loading, reference building, runner invocation, execution, scoring, failure logging, baseline comparison, and reporting.

## Current Test Case Shape

The benchmark no longer treats raw `{op, params}` lists as the primary fixture contract.

The canonical case model in `schema.py` now centers on:

- `fixture_version`
- `id`
- `category`
- `difficulty`
- `voice_commands`
- `initial_scene`
- `expected_steps`
- `reference_policy`
- `quality_signals`
- optional `target_mesh`
- optional compatibility `ground_truth`
- optional `compiled_payloads`
- optional `metadata`

`initial_scene` can now describe:

- `active`
- `mode`
- `screenshot`
- `objects`

The `objects` seed list lets the harness reconstruct a richer initial scene than the old single special-case cube setup.

### Canonical v2 Example

```json
{
  "fixture_version": "2.0",
  "id": "TS-INT-042",
  "category": "Transformations & Editing",
  "difficulty": "Medium",
  "voice_commands": [
    "Bevel the edges of this cube by 0.1 meters with 3 segments",
    "Give the cube a slight bevel, about point one meters and three cuts",
    "Round the corners of the box a bit",
    "Bevel this cube a little with three segments"
  ],
  "initial_scene": {
    "active": "Cube",
    "mode": "EDIT",
    "objects": [
      {
        "primitive": "CUBE",
        "name": "Cube",
        "location": [0.0, 0.0, 0.0],
        "rotation": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0]
      }
    ]
  },
  "expected_steps": [
    {
      "kind": "BEVEL",
      "args": {
        "offset": 0.1,
        "segments": 3,
        "profile": 0.5
      }
    }
  ],
  "reference_policy": {
    "mode": "dynamic",
    "repeat_runs": 2,
    "require_typed_coverage": true
  },
  "quality_signals": {
    "quad_ratio_min": 0.85,
    "manifold": true,
    "chamfer_threshold": 0.001
  }
}
```

Source: `testing/benchmark/fixtures/sample_cases_v2.json`

## How To Use Your Own JSON Test Case

The current docs already explain what the benchmark is and where it runs, but the practical workflow is:

1. Turn your scenario into a benchmark suite JSON file.
2. Validate that the file matches the benchmark schema.
3. Run the suite inside Blender with a benchmark runner.
4. Read the generated Markdown/JSON reports.

### 1. Put your case into suite format

Even if you only have one case, the harness expects a suite-shaped JSON payload. The easiest pattern is one file under `testing/benchmark/fixtures/` with one case in `cases`.

Minimum practical fields for one case:

- `id`
- `category`
- `difficulty`
- `voice_commands`
- `initial_scene`
- `expected_steps`
- `reference_policy`
- `quality_signals`

Example:

```json
{
  "suite_id": "my_first_suite",
  "fixture_version": "2.0",
  "prompt_template_version": "benchmark-execution-v1",
  "cases": [
    {
      "fixture_version": "2.0",
      "id": "MY-CASE-001",
      "category": "Object Creation",
      "difficulty": "Short",
      "voice_commands": [
        "Add a cylinder with 32 vertices"
      ],
      "initial_scene": {
        "active": null,
        "mode": "OBJECT"
      },
      "expected_steps": [
        {
          "kind": "ADD_MESH",
          "args": {
            "primitive": "CYLINDER",
            "vertices": 32,
            "radius": 1.0,
            "depth": 2.0
          }
        }
      ],
      "reference_policy": {
        "mode": "dynamic",
        "repeat_runs": 2,
        "require_typed_coverage": true
      },
      "quality_signals": {
        "quad_ratio_min": 0.0,
        "manifold": true,
        "chamfer_threshold": 0.001
      }
    }
  ]
}
```

Important notes:

- `compiled_payloads` is optional. The loader will derive it from `expected_steps`.
- Legacy `ground_truth` payloads are still accepted for compatibility and will be normalized into `expected_steps`.
- A plain scenario description by itself is not enough. The benchmark needs executable `expected_steps` or compatible legacy `ground_truth` so it can build a reference result.

### 2. Stay inside the supported benchmark step catalog

The current benchmark-safe canonical step set is:

- `ADD_MESH`
- `SET_MODE`
- `TRANSLATE`
- `SCALE`
- `ROTATE`
- `BEVEL`
- `INSET`
- `EXTRUDE_REGION`
- `SET_CAMERA`
- `SET_MATERIAL`

If your case needs operations outside this subset, the harness will usually report a coverage gap rather than execute an unsafe fallback.

### 3. Validate the JSON outside Blender first

Before launching Blender, validate that the suite loads cleanly:

```bash
python3 -c "from testing.benchmark.schema import TestSuite; s = TestSuite.from_json('testing/benchmark/fixtures/my_first_suite.json'); print(s.suite_id, len(s.cases))"
```

If this prints the suite id and case count, the schema loaded successfully.

### 4. Run the suite inside Blender

If you want to benchmark a live model backend, the recommended approach today is a small wrapper script modeled after `testing/benchmark/test_run.py`. That wrapper should:

- load your suite path
- construct `NalanaTestHarness`
- choose a runner such as `XmlRpcModelRunner`
- call `run_suite(...)`
- print the generated report paths

Minimal example:

```python
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from model_runners import XmlRpcModelRunner
from schema import OutputContract
from test_harness import NalanaTestHarness

suite_path = os.path.join(current_dir, "fixtures", "my_first_suite.json")

harness = NalanaTestHarness(suite_path)
runner = XmlRpcModelRunner(
    "http://127.0.0.1:8785/RPC2",
    method_name="generate_json_payload",
    payload_style="prompt_only",
    model_id="my-model",
    output_contract=OutputContract.LEGACY_OPS,
)

run = harness.run_suite(runner)
print(run.report_markdown_path)
print(run.report_json_path)
```

Then run it with Blender in background mode:

```bash
blender --background --python testing/benchmark/run_my_suite.py
```

Use:

- `OutputContract.LEGACY_OPS` if the model returns `[{\"op\": ..., \"params\": ...}]`
- `OutputContract.TYPED_COMMANDS` if the model returns `[{\"type\": ..., \"args\": ...}]`
- `OutputContract.NORMALIZED` if the model returns canonical benchmark steps

### 5. Replay precomputed JSON without calling a live model

If you already have model output JSON and just want to test it, use `StaticPayloadRunner` instead of XML-RPC. This is the easiest way to replay one case deterministically.

Example shape:

```python
from model_runners import StaticPayloadRunner
from schema import OutputContract

runner = StaticPayloadRunner(
    {
        "MY-CASE-001": '[{"type":"ADD_MESH","args":{"primitive":"CYLINDER","vertices":32,"radius":1.0,"depth":2.0}}]'
    },
    model_id="replay-test",
    output_contract=OutputContract.TYPED_COMMANDS,
)
```

### 6. Read the outputs

After a run, look in:

- `testing/benchmark/results/` for per-run `report.md` and `report.json`
- `testing/benchmark/artifacts/benchmark_failures.jsonl` for failed-attempt logs
- `testing/benchmark/baselines/` for the persisted Gemini baseline snapshot

### 7. If this case should become trusted synthetic ground truth

If your JSON case is meant to become part of the benchmark corpus rather than just a temporary test, validate it through `synthetic_ground_truth.py`. That pipeline compiles the case, builds the reference scene, checks determinism, and either accepts or quarantines it.

## Current Input and Output Contracts

### Input Side

The benchmark input now consists of:

- one voice-command variant from `voice_commands`
- the structured `initial_scene`
- the canonical `expected_steps`
- `reference_policy`
- `quality_signals`

### Output Side

The benchmark accepts three model-output shapes:

1. normalized benchmark steps

```json
[
  {
    "kind": "ADD_MESH",
    "args": {
      "primitive": "CYLINDER",
      "vertices": 32,
      "radius": 1.0,
      "depth": 2.0
    }
  }
]
```

2. legacy Blender-op payloads

```json
[
  {
    "op": "bpy.ops.mesh.primitive_cylinder_add",
    "params": {
      "vertices": 32,
      "radius": 1.0,
      "depth": 2.0
    }
  }
]
```

3. typed production commands

```json
[
  {
    "type": "ADD_MESH",
    "args": {
      "primitive": "CYLINDER",
      "vertices": 32,
      "radius": 1.0,
      "depth": 2.0
    }
  }
]
```

The harness normalizes any of these shapes into canonical `NormalizedStep` objects before scoring.

## Current Metrics

The benchmark now tracks and reports these core signals:

- `execution_success`
- `geometry_success`
- `command_accuracy`
- `parameter_accuracy`
- `sequence_accuracy`
- `quad_ratio`
- `manifold`
- `chamfer_distance`
- `model_latency_ms`
- `execution_latency_ms`
- `total_latency_ms`
- `Pass@1`
- `Pass@k`

The report layer also aggregates:

- category breakdowns
- difficulty breakdowns
- top failure reasons
- baseline deltas vs Gemini 3 Pro

## Current Grading Flow

The grading flow in `test_harness.py` is now:

1. Load the suite through `TestSuite.from_json()`.
2. For each case, build a reference result by:
   - resetting Blender
   - reconstructing `initial_scene`
   - executing `expected_steps`
   - capturing a `SceneSnapshot`
   - repeating the process `reference_policy.repeat_runs` times
3. Reject the case as a reference error if repeated reference runs are not deterministic.
4. For each voice-command attempt:
   - build a benchmark prompt through a `ModelRunner`
   - invoke the configured model/backend
   - normalize the returned payload into canonical steps
5. If parsing fails, record a `PARSE_ERROR`.
6. If parsing succeeds:
   - reset the scene again
   - execute the candidate payload through the contract-aware executor
7. Execution uses one of three paths:
   - typed-command execution through `addon.command_exec.execute_command`
   - legacy-op execution through the benchmark’s allowlisted registry
   - auto mode that prefers typed coverage and falls back to legacy only when needed
8. During execution, the benchmark enforces:
   - max command count
   - max step runtime
   - max new-object quota
   - max vertex quota
9. After execution, the harness captures a candidate `SceneSnapshot`.
10. The scorer computes:
    - command accuracy
    - parameter accuracy
    - sequence accuracy
    - quad ratio
    - manifold
    - Chamfer distance
    - pass/fail status against `quality_signals`
11. The harness aggregates attempts into per-case:
    - `Pass@1`
    - `Pass@k`
    - failure summaries
12. The reporter computes run summaries, stores or loads the Gemini baseline snapshot, writes:
    - `report.md`
    - `report.json`
13. Failed attempts are logged to `testing/benchmark/artifacts/benchmark_failures.jsonl` using normalized safe data rather than raw DPO preference pairs.

## Production Alignment

The benchmark is much closer to the production command path than before.

### Where It Aligns

- The benchmark has a typed-command path that now exercises the production executor in `addon/command_exec.py`.
- The production command schema has been expanded to include:
  - `SET_MODE`
  - `EDIT_MESH`
- Production safety now validates more of the safe modeling subset:
  - `ADD_MESH`
  - `TRANSFORM`
  - `SET_MODE`
  - `EDIT_MESH`
  - `SET_MATERIAL`
  - `SET_CAMERA`
- The benchmark’s canonical step catalog compiles directly into this safe subset.

### Where It Still Intentionally Diverges

- The canonical benchmark source of truth is `expected_steps`, not the production command dictionary itself.
- The benchmark still supports legacy Blender-op JSON because Nalana’s current execution-stage testing needs to compare older raw-op outputs as well as typed outputs.
- The legacy path is no longer arbitrary `getattr` dispatch; it is limited to a strict registry of approved operations.

## Safety Model

The benchmark is materially safer than the old raw-op harness.

Key changes:

- no arbitrary path traversal through `getattr`
- no free-form acceptance of any `bpy.` path
- only allowlisted legacy operators are executable
- typed commands are routed through production safety validation
- scene growth is constrained by quotas
- step runtime is constrained by timeouts
- unsupported commands surface as coverage gaps instead of silently executing risky fallbacks

## Synthetic Ground Truth

The benchmark now includes a verified-subset synthetic-ground-truth pipeline.

The intended workflow is:

1. Generate or draft a benchmark case in canonical `expected_steps` form.
2. Compile it to legacy and typed representations.
3. Build the reference scene repeatedly.
4. Require deterministic geometry signatures.
5. Accept the case into the synthetic fixture folder only if validation passes.
6. Otherwise quarantine it for repair or review.

This deliberately does not assume raw LLM output is correct just because it parses.

## Remaining Gaps and Risks

The benchmark is significantly stronger, but a few gaps remain:

1. Multimodal scoring is still out of scope.
   `initial_scene.screenshot` is preserved, but there is no multimodal metric yet.

2. Production telemetry metrics are still missing.
   The benchmark does not yet measure accepted rates, undo/keep behavior, or proportional usage.

3. Suite scale is not enforced.
   The code supports the new architecture, but it does not force the 100–200 curated case target.

4. Typed production coverage is still a safe subset.
   The benchmark records coverage gaps rather than pretending every canonical step is expressible by every production command path.

5. Success-target evaluation is still descriptive rather than policy-enforced.
   The reporter computes baseline deltas, but it does not yet declare a hard pass/fail against configurable threshold targets.

6. The benchmark code is implemented, but one full headless Blender validation loop is still the right next step.
   The pure-Python verification passed during implementation, but the final confidence check is an actual Blender run using the upgraded suite.

## Bottom Line

The benchmark is no longer just a raw Blender-op execution checker.

It now has:

- a canonical versioned fixture format
- dual-contract output handling
- deterministic dynamic references
- real command, parameter, sequence, geometry, and latency scoring
- immutable Gemini baseline support
- Markdown and JSON reporting
- a safer execution model
- a validated synthetic-ground-truth pipeline

The biggest remaining work is now mostly around benchmark scale, multimodal and telemetry coverage, and live Blender validation rather than core benchmark architecture.
