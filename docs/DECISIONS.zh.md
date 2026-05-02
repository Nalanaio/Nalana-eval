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
- 本 ADR 是暂定的；预计 Task #13 落地后 ~1 个月内会被升级为永久决策或被后续 ADR 替代。

---

## ADR-005 — 测试用例分类法：砍 TaskLength、加 SceneComplexity、空间一致性走 L3 判官

**日期**：2026-04-30
**状态**：Active
**Supersedes**：`nalana_eval.schema.Difficulty` 的隐式语义（保留 deprecated 1 周期，v3.2 删除）
**Depends on**：`ian/judge-empty-scene-guard` PR 必须**先**于 #13.2 audit 合并（否则空场景幻觉污染新判官指标）
**Blocks**：#13.1（schema 字段新增）、#13.2（现有 fixture 重新审计）

### Context

PR-A 端到端验证（2026-04-29）+ Q3 prototype 实验（Task #22, 2026-04-30）暴露了现有 `Difficulty: Short | Medium | Long` 字段的两个问题：

1. **`Difficulty` 把三个独立维度搅成一锅** —— prompt 啰嗦度、场景复杂度、判分难度。PR-A audit 发现 CV-AMB-004 "Make a simple house" 标的 `Long`，但实际场景就是 cube + cone——任何合理标准下都是 inexpensive 任务。`Difficulty` 字段最初的作者意图是 "step count"，跟 v2 ground-truth-step-replication 是同一思路——V3 已经明确抛弃。

2. **Compositional case 的空间一致性现在测不了**（比如 "Build a simple table"）—— hard `mesh_object_count >= 2` 让"5 个 cube 堆在原点"这种 pathological output 也能过 L2。Task #22 prototype 验证 L3 judge **能**在非空场景上区分 coherent vs incoherent 输出——前提是空场景幻觉 guard 先 ship。

由此驱动两件事：用更清晰的轴替代糊涂的 `Difficulty`、把空间一致性评估从 L2（约束）转到 L3（判官）。

### Decision

#### 1. 砍掉 `TaskLength` 轴（设计阶段拒绝）

最初提议作为 prompt 啰嗦度版本的 `Difficulty` 替代。直方图统计现有 80 prompts（每 case 取最短变体）显示 100% 集中在 3-9 词区间——这个轴会变成常数列，零信号。词数在 8K+ context 时代也不是 model 负担的好代理。轴在 land 之前就砍掉。

#### 2. 加 `SceneComplexity` 轴（手写 — Q4）

```python
class SceneComplexity(str, Enum):
    SINGLE_OBJECT = "single_object"   # 1 mesh
    MULTI_OBJECT  = "multi_object"    # 2–5 mesh，无空间关系要求
    COMPOSITION   = "composition"     # 2+ mesh，作者**意图**要求空间结构（例如桌子=面在腿上）；
                                      # 强制实施由 L3 判官负责，**不是** hard relative_positions 约束
    FULL_SCENE    = "full_scene"      # 5+ mesh + 材质，完整环境
```

`scene_complexity` 是 `TestCaseCard` 上的**必填字段**，反映**作者意图**——**不是**从约束形状推出来的。作者意图和约束形状可以**故意**分离——一个 stylized "未来感桌子" case 可以标 COMPOSITION 但约束放宽，给模型留创意空间。这种解耦让 `tools/drift_check.py`（#13.4）能抓"标 vs 约束"不一致的 fixture bug——如果字段是从约束自动推的，这种信号永远丢失。

#### 3. COMPOSITION case 的空间一致性走 L3 判官（Q3——Task #22 数据）

对标 COMPOSITION 的 case **不要**加 `hard_constraints.relative_positions` 强制空间关系。硬约束杀死创造性解读（hammock 椅、艺术装置倒挂桌都会 FAIL）。改用：

- `judge_policy: "score"`（不要 `skip`）
- `style_intent.acceptable_styles` 扩到 ≥3 个创意选项（如 `["realistic", "minimalist", "stylized", "futuristic", "geometric"]`）
- 信任多模态 LLM 判官识别"这是 table 类组合 vs 5 个 cube 堆原点"

Schema 现有 `relative_positions` 字段保留作 **opt-in**，留给"工业 CAD 精度"这类未来 category。`relative_positions` 的 evaluator 实现推迟到那种 case 真的出现时再做。

#### 4. 弃用现有 `Difficulty` 字段（Q1）

```python
class TestCaseCard:
    scene_complexity:  SceneComplexity              # NEW, required
    difficulty:        Optional[Difficulty] = None  # DEPRECATED——v3.2 删除
```

现有 80 fixture 在 deprecation 周期里保留 `difficulty` 值；新 fixture（#13.3+）不再填这个字段。CLI flag `--difficulty-dist` 保持能用但发出 deprecation warning。所有 fixture 迁移完之后下个周期删掉。

### 现有 80 fixture 迁移（在 #13.2 执行——Q5 strict 模式）

audit 同一个 batch commit 里做三件事：

1. 给每个 case 基于人工判断加 `scene_complexity` 字段（~30 秒/case = 80 case 共 ~40 分钟）
2. 标 `scene_complexity: "composition"` 或 `"full_scene"` 的 case：
   - 翻 `judge_policy: "skip"` → `"score"`
   - 扩 `style_intent.acceptable_styles` 到 3+ 创意选项
3. 在 #13.2 PR description 里逐 case 记录 re-tag 和 policy-flip 决定

预计影响：
- 现有 80 中约 10-15 个 case 重新标为 COMPOSITION/FULL_SCENE
- 单 200-case run 成本从 ~$3（当前，多数 skip）涨到 ~$10（~25/80 是 score）
- `docs/USAGE_GUIDE.md` 的 cost-projection 表在 #13.2 PR 里同步更新

### Consequences

- **Schema** 加一个字段（`scene_complexity`）、弃一个字段（`difficulty`）。迁移渐进（1 个周期，不破坏）。
- **作者负担**：每 case 多 ~5 秒填新字段。LLM-assisted authoring（#13.3）从 draft 自动填 `scene_complexity`。
- **Drift check（#13.4）** 多一条规则：当 `scene_complexity` 和 `hard_constraints` 形状不一致时 warn（例如标 COMPOSITION 但 `mesh_object_count.minimum < 2`）。
- **报告** 多 "by scene complexity" 分组表；"by difficulty" 表标 deprecated。
- **Benchmark 成本涨 ~3.5×**（含 composition/full-scene case 的 run）。已记录、接受。
- **L3 判官的可靠性现在更重要** —— 空场景幻觉 guard PR 是 #13.2 strict 模式 audit 的**硬前置**。没修这个，新的 judge-based 指标会被空场景幻觉系统性拉高。
- **ADR-004 retry-with-feedback 重评估门槛（#13.12）变得更有意义**：hard composition case 会产生有真实 judge 信号的真实 failure，retry loop 的实际效用终于可以在不被 mock 主导的数据上测量。
