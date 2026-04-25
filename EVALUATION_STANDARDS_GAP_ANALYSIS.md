# Evaluation Standards vs Current Benchmark Code

This memo compares the expectations in `Model Performance Evaluation Standards Framework Proposal` against the current benchmark implementation after the dual-contract upgrade.

Primary benchmark files:

- `testing/benchmark/schema.py`
- `testing/benchmark/contracts.py`
- `testing/benchmark/executor.py`
- `testing/benchmark/metrics_evaluator.py`
- `testing/benchmark/model_runners.py`
- `testing/benchmark/reporting.py`
- `testing/benchmark/test_harness.py`
- `testing/benchmark/synthetic_ground_truth.py`
- `testing/benchmark/fixtures/sample_cases_v2.json`

Related production files:

- `nalana_core/commands/schema.py`
- `nalana_core/commands/safety.py`
- `addon/command_exec.py`

Status labels used here:

- **Implemented**: present and wired end to end in code
- **Partially Implemented**: present, but still scoped down or missing part of the proposal
- **Not Implemented**: absent from the current codebase

Note:

- This document reflects the code that exists in the repo now.
- It does not claim that every Blender-only path has already been validated in a live headless Blender run.
- Multimodal scoring remains intentionally out of scope for the current implementation pass.

## Standards Expectations

The standards document expects a benchmark with:

- a **100–200 case** JSON suite stratified by category and difficulty
- per-case data including **natural-language input**, **initial scene context**, **mock screenshots**, **mesh stats**, **ground-truth operations**, and the **target 3D result**
- core metrics including **Execution Success**, **Command Accuracy**, **Parameter Accuracy**, **Geometric Accuracy / Chamfer**, **Latency**, and **Multimodal Reasoning Score**
- engagement metrics including **Production accepted rates** and **Proportional Usage**
- an automated **JSON -> XML-RPC -> Blender** route with safe dispatch
- **Gemini Pro 3** as the baseline model
- higher-level metrics such as **Resolution Rate**, **Pass-to-Pass**, **Sequence Accuracy**, and **Acceptance / Engagement**

## Comparison Table

| Standard | Expected | Current code | Status |
|---|---|---|---|
| Test suite scale | 100–200 curated cases | The new architecture supports larger suites, but there is still no minimum-size enforcement and the checked-in sample suite is intentionally small | Not Implemented |
| Category + difficulty stratification | Cases grouped by category and difficulty | `Category` and `Difficulty` remain first-class fixture fields | Implemented |
| Natural-language input | Per-case NL commands | `voice_commands` remains a required case field and drives attempt generation | Implemented |
| Initial scene context | Structured preconditions | `InitialScene` now supports `active`, `mode`, `screenshot`, and seeded `objects` | Implemented |
| Mock viewport screenshots | Screenshot-aware cases | Screenshot context is preserved in the schema, but there is still no screenshot-conditioned grading path | Partially Implemented |
| Mesh stats in test cases | Per-case mesh stats included | Mesh statistics now exist in runtime `SceneSnapshot` and `SceneMeshSnapshot` artifacts, but they are not authored as fixture input fields | Partially Implemented |
| Ground-truth operations | Expected operation sequence per case | Cases now use canonical `expected_steps`, with compiled legacy and typed payloads available alongside compatibility `ground_truth` | Implemented |
| Target 3D result | Per-case target result | Target results are now built dynamically via deterministic reference generation; `target_mesh` is optional for static assets | Implemented |
| Execution Success | Output must parse, validate, and execute safely | Parse, normalization, safety, execution, and failure classification are all wired into the harness | Implemented |
| Command Accuracy | Correct command selection | Calculated from normalized expected vs candidate step kinds | Implemented |
| Parameter Accuracy | Correct arguments | Calculated from normalized step arguments with numeric tolerances | Implemented |
| Geometric Accuracy | Final-result similarity | Real geometry scoring now combines quad ratio, manifold, and Chamfer distance against the reference snapshot | Implemented |
| Quad Ratio | Topology quality | Computed from captured scene snapshots and used in grading | Implemented |
| Manifold | Water-tightness / topology quality | Computed from scene snapshots and used in grading | Implemented |
| Chamfer Distance | Exact geometric similarity | Implemented in NumPy with deterministic point sampling and vertex fallback | Implemented |
| Pass@1 | First-attempt success | Computed per case and summarized per run | Implemented |
| Pass@k | At-least-one-success in k attempts | Computed per case and summarized per run | Implemented |
| Pass-to-Pass / regression safety | Detect regressions across benchmark revisions | The benchmark now persists Gemini baseline snapshots and delta views, but it still does not explicitly track pass-set deltas across code revisions | Partially Implemented |
| Resolution Rate | Full-case resolution metric | Cases now have explicit `passed` state and `Pass@k`, but there is still no dedicated `resolution_rate` metric label in reporting | Partially Implemented |
| Sequence Accuracy | Correct multi-step order | Implemented via normalized-step sequence comparison | Implemented |
| Latency | Timed evaluation | The benchmark records model, execution, and total latency; it does not yet time the full STT-to-execution voice pipeline | Partially Implemented |
| Multimodal Reasoning Score | Screenshot-dependent scoring | Screenshot context exists, but there is no multimodal scoring metric yet | Not Implemented |
| Production accepted rates | Undo/keep telemetry | No production telemetry is captured by the benchmark | Not Implemented |
| Proportional Usage | AI-vs-manual usage share | No production workflow telemetry is captured by the benchmark | Not Implemented |
| Turn Duration / autonomy | Long-horizon autonomy measure | The benchmark records latency only; it does not score autonomy or sustained multi-turn completion | Not Implemented |
| JSON -> XML-RPC -> Blender route | Automated route into Blender | Implemented through XML-RPC model runners and Blender-side execution | Implemented |
| Safe JSON dispatcher | Secure execution | Implemented with normalized parsing, allowlisted legacy dispatch, typed-command safety validation, quotas, and timeouts | Implemented |
| Gemini baseline | Benchmark Gemini Pro 3 first | Implemented through `GeminiRunner`, `BaselineStore`, and per-run baseline delta reporting | Implemented |
| Success targets | Beat baseline on execution/geometric accuracy/latency | Baseline deltas are computed and reported, but there is no configurable threshold policy yet | Partially Implemented |
| Synthetic ground truth | Safe way to create benchmark references | Implemented through the verified-subset validator and quarantine flow in `synthetic_ground_truth.py` | Implemented |

## Implemented In Current Code

The following proposal expectations are now implemented directly in code:

- versioned benchmark fixtures with canonical `expected_steps`
- compatibility loading from legacy raw-op fixtures
- safe canonical step validation and dual compilation
- typed production-command benchmarking alongside legacy raw-op benchmarking
- deterministic dynamic reference generation
- execution success, command accuracy, parameter accuracy, and sequence accuracy
- real geometry scoring with quad ratio, manifold, and Chamfer distance
- model, execution, and total latency tracking
- `Pass@1` and `Pass@k`
- per-run Markdown and JSON reporting
- immutable Gemini baseline persistence and delta reporting
- synthetic-ground-truth validation with accept/quarantine behavior

## Partially Implemented

These areas have real support, but they do not yet fully meet the proposal’s largest version of the requirement.

- Screenshot support exists in fixtures, but there is no multimodal metric.
- Mesh stats are captured dynamically in runtime artifacts rather than authored directly into case fixtures.
- Baseline deltas exist, but there is no threshold policy that says whether a candidate “officially beats” the baseline.
- Pass-to-pass style regression visibility exists indirectly through baselines and reports, but not as a dedicated regression metric.
- Latency is measured for the benchmark execution path, not the entire live voice workflow.
- Resolution-rate semantics are represented indirectly through pass/fail results and `Pass@k`, not as a separately named top-level metric.

## Not Yet Implemented

These proposal items are still outside the benchmark’s current scope.

- enforced 100–200 case suite scale
- multimodal reasoning score
- production accepted/undo telemetry
- proportional usage telemetry
- autonomy / turn-duration metrics

## Bottom Line

Before the upgrade, the benchmark was mostly an execution-and-topology checker built around raw Blender-op JSON.

After the upgrade, the benchmark now covers most of the proposal’s **mechanical evaluation framework**:

- canonical fixtures
- dual-contract execution
- dynamic reference generation
- safe execution
- accuracy metrics
- geometry metrics
- latency metrics
- baseline storage
- structured reporting
- synthetic-ground-truth validation

The biggest remaining gaps are now mostly in:

- benchmark corpus scale
- multimodal scoring
- production telemetry
- hard success-threshold policy

So the codebase is now much closer to the intended evaluation framework, and the remaining work is primarily about coverage breadth and rollout signals rather than missing core benchmark infrastructure.
