# Legacy V2 Ground-Truth System

These files are from the **v2.0 ground-truth-focused evaluation system** and have been superseded by the `nalana_eval/` v3.0 package at the repository root.

They are kept here for historical reference only. **Do not import or run these files in new code.**

---

## Why archived

The v2 system was organized around manually curated ground-truth model outputs and a monolithic
evaluation script. V3.0 replaces it with:

- A schema-validated `TestCaseCard` fixture format (`nalana_eval/schema.py`)
- A constraint-based `ConstraintEvaluator` that doesn't require pre-recorded outputs
- A multimodal LLM-as-Judge for open-ended tasks
- A persistent CSV audit trail and structured artifact tree

The compatibility bridge for loading v2 fixtures into the v3 pipeline is `nalana_eval/legacy_schema.py`.

---

## File inventory

| File | Description |
|------|-------------|
| `schema.py` | V2 Pydantic models for test cases and ground-truth outputs |
| `contracts.py` | V2 LLM output contract normalization (NORMALIZED / LEGACY_OPS / TYPED_COMMANDS) |
| `executor.py` | V2 Blender command executor |
| `model_runners.py` | V2 model runner classes (OpenAI / Anthropic / Gemini) |
| `metrics_evaluator.py` | V2 metric computation logic |
| `reporting.py` | V2 report generation |
| `run_evaluation.py` | V2 top-level evaluation entry point |
| `synthetic_ground_truth.py` | V2 synthetic ground-truth generator |
| `test_harness.py` | V2 test harness runner |
| `test_run.py` | V2 ad-hoc test run script |
| `BENCHMARK_AUDIT.md` | V2 benchmark audit notes |
| `Code_Base_Procedure.txt` | V2 codebase procedure documentation |
| `Code_Base_Structure.txt` | V2 codebase structure notes |
| `EVALUATION_STANDARDS_GAP_ANALYSIS.md` | V2 evaluation standards analysis |
| `MULTI_MODEL_EVALUATION_PLAN.md` | V2 multi-model evaluation plan |
| `VOICE_TRANSLATION_AUDIT.md` | V2 voice translation audit |
