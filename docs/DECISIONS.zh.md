# 决策档案（Decision Log）

> 只追加不修改的决策日志。每条是一个轻量级 ADR（context / decision / consequence）。不要改历史——要修正一条旧决策，就追加一条新的"supersedes"它。

**English version**: [`DECISIONS.md`](DECISIONS.md)

---

## ADR-001 — Synthetic generator 接走 50–80 条简单 case；LLM 起草接 150–250 条复杂 case

**日期**：2026-04-26
**状态**：Active
**Supersedes**：GitHub issue *"generate 200-300 test cases using grok/deepseek"* 的部分范围
**相关 task**：[#13](../) Test case authoring pipeline

### Context

V3.0 的 L2 benchmark 上线目标 200–300 case，长期到 1000+。原 issue 计划全部用外部 LLM（grok / deepseek 之类）生成。在探索过程中我们写了一个程序化 synthetic 生成器（`fixtures/synthetic/generate_cases.py`，commit `35c05ad`），用 primitive × color × size 笛卡儿积确定性地产出 50 条 case。

问题：这个 generator 能不能完全平替原 issue？

### Analysis

Generator 的强项和限制：

| 维度 | Synthetic generator | LLM 起草 |
|---|---|---|
| 确定性 / 可复现 | ✅ 同输入永远同输出 | ❌ 即便给 seed 也有随机性 |
| 约束精度 | ✅ bbox / RGBA 预算好的 | ❌ prompt 与 constraint 容易漂移 |
| 简单 case 覆盖 | ✅ Object Creation、Materials & Shading | 大材小用 |
| 复杂 case 覆盖 | ❌ 写不出 Stylized / Multi-Object / Edit | ✅ 这才是它的强项 |
| `judge_policy: score` 覆盖 | ❌ 全部 `skip` | ✅ L3 测试必需 |
| 成本 | 零 | ~$0.01-$0.10 / case |

Generator 是 **constraint-first**（从约束模板出发填 prompt）。复杂 case 需要 **concept-first**（从用户场景出发倒推约束）。架构上不可替代。

### Decision

把原 issue 拆成两部分：

- **50–80 条简单 case**（Object Creation primitives、materials、parameterized primitives）→ synthetic generator 接走，commit `35c05ad` 完成。
- **150–250 条复杂 case**（Stylized Modeling、Multi-Object Composition、Edit Operations、Complex Workflows，全部 `judge_policy: score`）→ 折进 task #13 的扩展 scope："Test case authoring pipeline"（LLM 起草 → schema 校验 → drift 检测 → honeypot 注入 → 抽样人审 → 入库 `fixtures/llm_authored_v3/`）。

原 GitHub issue 关闭，附评论指向 commit `35c05ad`（简单 case 部分）和 issue #13（复杂 case 部分）。

### Consequences

- `fixtures/synthetic/` 是低成本、确定性 primitive/material case 的权威归处。
- `fixtures/llm_authored_v3/`（在 #13 里建）放复杂 case。
- `fixtures/starter_v3/` 保留 30 条手写种子 case。
- 避免未来出现"全部交给 LLM 生成"的回炉提议——回链到这条 ADR。

---

## ADR-002 — 评测输出（artifacts/、db/、calibration/baseline_results/）已在 .gitignore 覆盖

**日期**：2026-04-27
**状态**：Active
**已验证**：`git check-ignore -v` + `git ls-files | grep`

### Context

团队成员提出担忧：评测 run 的输出（每 run 的截图、场景统计 JSON、累积的 CSV 历史、判官缓存）如果不小心 commit 进 git 会膨胀仓库——多次 run 累积可达几百 MB。

### Decision

`.gitignore` 第 11–23 行覆盖了所有评测输出：

```
# Run artifacts (per-run output folders)
artifacts/

# Local database (CSV files, judge cache)
db/*.csv
db/*.sqlite
db/*.sqlite-journal
!db/.gitkeep

# Calibration baseline results (these are local-only)
calibration/baseline_results/
calibration/reference_images/*
!calibration/reference_images/.gitkeep
```

`db/.gitkeep` 和 `calibration/reference_images/.gitkeep` 故意不忽略，让目录结构在新 clone 里能保留。

### Verification

2026-04-27 验证：

```bash
git check-ignore -v artifacts/ db/runs.csv db/judge_cache.sqlite \
                    calibration/baseline_results/ calibration/reference_images/foo.png .env
# 全部命中正确的 .gitignore 行

git ls-files | grep -E "^(artifacts/|db/.*\.(csv|sqlite)|calibration/baseline_results/)"
# （空）—— git 里没有任何 eval 产物被 track
```

### Consequences

- 团队成员可以在本地随便跑 benchmark，不污染 git 历史。
- 未来新增评测输出目录类型，要主动加到 `.gitignore`。规则：凡是 `python -m nalana_eval.cli` 跑出来的东西都该进 `.gitignore`。
- 这条决策针对的是系统的 *输出*。*输入* 制品（测试用例、prompts、校准说明书）继续 track 在 git 里。
