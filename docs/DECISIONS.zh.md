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

---

## ADR-003 — 禁止 mixed-concerns PR

**日期**：2026-04-29
**状态**：Active
**警示案例**：PR #21（brian-test，2026-04-28）

### Context

PR #21 一个 merge 里塞了 4 件独立的事：

1. **Agentic retry-with-feedback loop**（行为新功能）
2. **`contracts.py` 多键 list-wrapper unwrap**（parser bug fix）
3. **`openai_runner.py` 受限模型条件化 `response_format`**（runtime bug fix）
4. **`prompts/eval_default.md` step-kind 文档全面补全**（prompt-engineering 改动，本身已标 "校准集影响：需要重跑 baseline"）

合并后 benchmark pass rate 从 0%（pre-PR）升到 100%（post-PR），团队最初把功劳算在 (1) retry loop 上。后续对 `db/attempts.csv`（n=119）和 `4-29runs/` aggregate（n=30 真实模型 retry）的回溯分析显示：loop 实际救活率 7.5%，集中在单个 run。**真正贡献的是 (4)** — prompt 全面补全教模型学会了正确的 NORMALIZED contract 格式，之前模型一直在猜（猜错）。PR #21 的捆绑让这个归因到事后人工考古才看出来。

这是**测量失败，不是代码质量失败**：4 件改动各自都是合理的。问题在于——包括作者和 reviewer 在内——没人能分辨哪件改动驱动了哪个观察到的效果。

### Decision

未来本仓库的 PR 必须**一次只做一件事**。

- "一件事" = 一个功能、一个 bug fix、或一次 refactor。与代码改动实质性配套的 ADR / 文档可以同 PR（例如新功能 ship 时附带它的 ADR 算一件事）。
- **Bug fixes 只在共享同一根因时才能合并。** "这三处都是同一个模块里的 bug" 可以；"这三处恰巧同时坏了" 不可以。
- `_TEMPLATE.md` handoff doc 的 *Scope* 段必须显式列 *In* 和 *Out* — 不在 *In* 里的事就是另一个 PR 的事。

当前的 cleanup PR（PR-A）允许打包 13 个 commit，因为它们共享同一根因 "post-PR-#21 cleanup，包括应该在 PR #21 之前就存在但当时没有的 docs/process 基础设施"。这条 ADR 本身就是这 13 commit 之一；它**对未来的 PR** 生效。

### Consequences

- 代码考古变可行：每次 lift / regression / 行为变化都能精确归因到一个 PR
- PR review 负担降低（PR 更小、diff 更窄）
- 作者要承担更多的 PR 创建开销。缓解方式：提供 `_TEMPLATE.md`、（以后）做一个 `/handoff` skill。
- 在 review 时把 "新功能 + 几个顺带修的小 bug" 这种 PR 拒掉、要求重新拆成多个 PR，即便代价是一天的返工。

---

## ADR-004 — Retry-with-feedback loop 默认 OFF；数据不足以验证

**日期**：2026-04-29
**状态**：Active（暂定 — Task #13 落地后再次评估）
**数据来源**：`db/attempts.csv`（host 端，4-28 runs）+ `4-29runs/` aggregate（Docker 端 runs）

### Context

PR #21 加了 `retry-with-feedback` 机制：当 `pass@k` 某次 attempt 失败，下次 attempt 的 prompt 会被加上结构化的失败摘要（failure class、执行了哪些 step、scene snapshot）。实现是**默认开**，套在 `pass@k` 循环外。

合并后浮现两个问题：
1. 这是不是破坏了 V3 "公平单 shot 比较模型" 的语义？
2. 它实际上有用吗？有用多少？

排除 mock 后的真实模型 retry 数据（mock 返回写死的输出，retry 不可能改变结果，所以它的 52 retry 0 saves 不算数）：

| 数据源 | Retry attempts | Retry 救活 | 救活率 |
|---|---|---|---|
| host `db/attempts.csv` | 10 | 0 | 0% |
| `4-29runs/` aggregate | 30 | 3 | 10% |
| **合计** | **40** | **3** | **7.5%** |

3 次救活全部集中在一个 run（`run_20260429_94b59e4e`，gpt-5.4）。其他 gpt-5.4 runs 和所有 gpt-5.5 runs 都是 0 saves。**lift 是集中且不稳定的，不是均匀的**。

PR #21 跟 retry loop 一起捆绑的还有 3 件改动（见 ADR-003）—— prompt 全面补全是那次 pass-rate lift 的更可能解释。

### Decision

- **默认 `--retry-with-feedback` OFF**。单 shot pass@k 是 V3 baseline 语义；要测 / 跑带 retry 的就显式开。
- **`failure_reason` 以 `"API error:"` 开头时 skip retry**。那是 auth / param / endpoint 配置错，retry context 救不了，只浪费 API 预算。
- **rescue rate / variance 等指标排除 mock 模型**。Mock 是 smoke-test fixture，不是真实评测对象。
- **`attempts.csv` 加 `had_retry_context: bool` 和 `iterations_taken: int` 两列**，让事后 loop ON-vs-OFF A/B 分析不用 rerun benchmark。

### 重新评估门槛

Task #13 落地 ≥30 个 hard case（定义：gpt-4 量级模型 attempt-0 失败率 ≥30% 的 case）之后，在同一份 case 集合上跑 `--retry-with-feedback` ON 和 OFF。决策规则：

- **hard case pass@3 lift ≥10pp** → 默认翻成 ON，ship 为 ADR-005
- **lift 5–10pp** → 默认保持 OFF；考虑重设计 retry context 格式（当前是 raw failure-reason + executed-steps + scene snapshot；可以考虑加入显式 constraint 文本和 step-kind 参数文档）
- **n≥30 时 lift <5pp** → 考虑删除。代码保留作 ad-hoc opt-in 但不再维护。

### Consequences

- V3 `pass@k` 数字跨 run、跨模型版本可比性保住。Brian 在 4-29runs 上看到的 5 case 100% 通过率，含义回到 "单 shot 这 5 个 case 100% 通过"，故事更清楚。
- 默认情况下单 case 成本回到单 shot baseline。开 retry 的用户知道自己在花 ~50% 多成本换 ~7.5% lift（当前 fixture 数据）。
- `--retry-with-feedback` 是显式 opt-in flag，特别想测 production 风格 "给模型第二次机会" 行为的用户一行 flag 就能开。
- 本 ADR 是暂定的；预计 Task #13 落地后 ~1 个月内会被升级为永久决策或被 ADR-005 替代。
