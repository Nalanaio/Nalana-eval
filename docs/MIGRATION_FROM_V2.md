# 从 v2.0 迁移到 v3.0

> 这份文档解释新旧两套评测系统的关系、迁移策略、共存方案。
> 适合**已有 v2.0 用例库的人**或**想理解为什么有两套 schema**的人。

---

## 1. v2.0 vs v3.0 速览

| 维度 | v2.0（旧） | v3.0（新） |
|---|---|---|
| **核心理念** | 复制人类操作步骤 | 满足客观约束 |
| **schema 主字段** | `expected_steps`, `ground_truth` | `hard_constraints`, `topology_policy`, `soft_constraints`, `style_intent` |
| **评估方法** | 步骤对比 + Chamfer Distance | 约束验证 + 拓扑检查 + LLM-as-Judge |
| **决定 pass/fail 的指标** | Command Accuracy + Parameter Accuracy + Geometric Accuracy | Hard Constraints + Topology Policy |
| **可规模化** | 否（每个 case 需手工录制 ground truth） | 是（约束可程序化生成） |
| **覆盖范围** | 确定性 + 创意（混在一起） | L1 确定性 + L2 创意（分层） |
| **当前用途** | L1 API 单元测试套件（保留） | L2 主 benchmark（核心） |

---

## 2. 为什么不直接删掉 v2.0

虽然 v3.0 是主 benchmark，**v2.0 仍然有不可替代的价值**：

### 2.1 确定性操作的精准回归保护

某些操作有**唯一正确答案**：

- "撤销" → 只能是 `bpy.ops.ed.undo()`
- "切换到编辑模式" → 只能是 `bpy.ops.object.mode_set(mode='EDIT')`
- "删除选中" → 只能是 `bpy.ops.object.delete()`
- "添加默认立方体" → 只能是 `bpy.ops.mesh.primitive_cube_add()` 不带任何参数

对这类操作，**步骤对比是最精准的测试**——v3.0 的约束检查反而会"测漏"（约束写"场景没有对象"既能通过 `bpy.ops.object.delete()` 也能通过 `bpy.ops.outliner.delete()`，但产品要求只能用 `delete()`）。

### 2.2 防回归红线

`Pass-to-Pass Rate = 100%` 是**红线指标**——模型更新后，之前通过的确定性用例**必须仍然通过**。这种"曾经做对的不能退步"的承诺，只有 v2.0 的步骤对比能精准度量。

### 2.3 现有 v2.0 fixtures 已经存在

`Nalana-datasc/testing/benchmark/fixtures/sample_cases_v2.json` 已经有一批用例。直接抛弃 = 浪费已有人工成本。

---

## 3. 迁移策略：B 选项（保留 + 共存）

> 用户在设计阶段选择了 **B 选项**：v2.0 缩水为 L1 单元测试套件，v3.0 是主 benchmark。

### 3.1 v2.0 的新角色：L1 单元测试套件

**保留范围**：仅限 `TaskFamily ∈ {scene_hygiene_safety, primitive_creation_default, mode_switching, camera_assignment_explicit}` 的确定性用例。

**清理范围**：删掉那些"步骤对比误判"的用例，例如：

- 创意类（`Compositional-Creative`）—— 移到 v3.0
- 模糊类（`Ambiguous/Contextual`）—— 移到 v3.0
- 带参数变化的 primitive（"创建半径 2 米的球"）—— 移到 v3.0（约束更适合）

**保留下来的 v2.0 用例数**：约 **50–100 条**（占原 v2.0 的 30%–50%）。

### 3.2 物理位置

```
fixtures/
├── starter_v3/                    ← 新版 v3.0（主 benchmark）
│   └── *.json
├── legacy_v2/                     ← 旧版 v2.0（L1 单元测试）
│   ├── sample_cases.json          ← 从 Nalana-datasc 复制
│   └── sample_cases_v2.json       ← 从 Nalana-datasc 复制（清理后）
└── synthetic/                     ← 程序化生成（v3.0 格式）
    └── generate_cases.py
```

### 3.3 CLI 调用

```bash
# 跑 v3.0 主 benchmark（默认）
python -m nalana_eval.cli --suite fixtures/starter_v3 --models gpt-5

# 跑 v2.0 legacy 单元测试套件（防回归）
python -m nalana_eval.cli --legacy-suite fixtures/legacy_v2/sample_cases_v2.json --models gpt-5

# 同时跑两个（推荐发版前流程）
python -m nalana_eval.cli --suite fixtures/starter_v3 --models gpt-5
python -m nalana_eval.cli --legacy-suite fixtures/legacy_v2/sample_cases_v2.json --models gpt-5
```

输出在不同的 run folder。CSV 数据库共享同一个，但行可以通过 `cli_args` 字段区分（含 `legacy_suite: true` 标记）。

### 3.4 schema 共存

代码层面：

- `nalana_eval/schema.py`：v3.0 schema（主 benchmark）
- `nalana_eval/legacy_schema.py`：v2.0 schema（原样保留，**不修改**）

加载时：

- v3.0 用例 → `TestSuite.from_json_or_dir()`
- v2.0 用例 → `LegacyReferenceSuite.from_json()`

错配会报 `LegacySuiteError`：

```
"This file is fixture_version=2.0 but you loaded it via TestSuite (v3.0).
Use LegacyReferenceSuite or pass --legacy-suite."
```

---

## 4. 迁移操作步骤（一次性）

### Step 1：复制 v2.0 fixtures 到新位置

```bash
mkdir -p /Users/ianian/Nalana-eval/fixtures/legacy_v2
cp /Users/ianian/Nalana-datasc/testing/benchmark/fixtures/sample_cases.json \
   /Users/ianian/Nalana-eval/fixtures/legacy_v2/
cp /Users/ianian/Nalana-datasc/testing/benchmark/fixtures/sample_cases_v2.json \
   /Users/ianian/Nalana-eval/fixtures/legacy_v2/
```

### Step 2：清理 legacy 用例

打开 `legacy_v2/sample_cases_v2.json`，**删除以下 case**：

- 所有 `category: "Compositional-Creative"`
- 所有 `category: "Ambiguous/Contextual"`
- 带参数变化的 `category: "Object Creation"`（保留无参数 primitive）
- `category: "Materials & Shading"` 中颜色非完整 RGBA 精确值的 case

**保留**：

- `Object Creation` 中无参数 primitive（"创建立方体"等）
- `Transformations & Editing` 中 seed 对象明确、变换确定的 case
- `Error Recovery & Safety` 全部
- `category: "Materials & Shading"` 中颜色完整精确（"把方块变成纯红 (1, 0, 0, 1)"）的 case

### Step 3：迁移有价值的 v2.0 创意用例到 v3.0 格式

把删掉的创意类用例**重写**为 v3.0 约束格式。例如：

**v2.0 原始**：
```json
{
  "id": "TC-CMP-005",
  "voice_commands": ["做一张桌子"],
  "expected_steps": [
    {"kind": "ADD_MESH", "args": {"primitive": "CUBE", "scale": [2, 1, 0.1]}},
    {"kind": "ADD_MESH", "args": {"primitive": "CYLINDER", "scale": [0.1, 0.1, 1]}},
    ...
  ]
}
```

**v3.0 重写**：
```json
{
  "id": "CV-CMP-0005",
  "category": "Compositional-Creative",
  "task_family": "simple_multi_object_composition",
  "prompt_variants": ["做一张桌子", "Create a table", "搭一张桌子"],
  "hard_constraints": {
    "mesh_object_count": { "minimum": 2 },
    "bounding_boxes": [{
      "target": "__scene__",
      "size_range": { "minimum": [0.5, 0.5, 0.3], "maximum": [3.0, 3.0, 2.0] }
    }]
  },
  "soft_constraints": [
    { "name": "对象数量合理", "metric": "total_mesh_objects", "direction": "min", "target": 3, "weight": 0.3 }
  ],
  "topology_policy": { "manifold_required": false, "quad_ratio_min": 0.0 },
  "style_intent": {
    "explicit": false,
    "concept": "table",
    "concept_aliases": ["desk"],
    "acceptable_styles": ["realistic", "stylized", "low-poly"]
  },
  "judge_policy": "score"
}
```

详细写法见 `TEST_CASE_AUTHORING.md`。

### Step 4：在 schema 校验下加载验证

```bash
# v3.0 用例校验
pytest tests/test_schema.py::test_load_starter_v3 -v

# v2.0 用例校验
pytest tests/test_schema.py::test_load_legacy_v2 -v
```

### Step 5：跑双轨 smoke test

```bash
# v3.0 主 benchmark
python -m nalana_eval.cli --cases 5 --suite fixtures/starter_v3 --models mock --simple-mode

# v2.0 legacy
python -m nalana_eval.cli --cases 5 --legacy-suite fixtures/legacy_v2/sample_cases_v2.json --models mock --simple-mode
```

两边都能跑通后，迁移完成。

---

## 5. 评测指标的对应关系

旧 v2.0 PDF 里的指标在新系统中怎么落地：

| 旧 v2.0 指标 | 新系统去向 |
|---|---|
| Resolution Rate | L2 `hard_pass_rate` |
| Pass@k | L2 `pass_at_3`（沿用） |
| Pass-to-Pass | L1 红线（保留，新系统用 v2.0 套件实现） |
| Command Accuracy | L1 metric（仅限 v2.0 套件） |
| Parameter Accuracy | L1 metric（仅限 v2.0 套件） |
| Geometric Accuracy (Chamfer) | L1 metric（仅当用例提供参考网格） |
| Execution Success | 升级为所有层级的基础门槛 |
| Quad Ratio / Manifold | L2 `topology_policy`（升级为正式约束） |
| Multimodal Reasoning Score | L2 `artifact_policy.require_screenshot` + L3 `judge_semantic` |
| Productions Accepted Rate | L3 Phase 3 隐性反馈（产品端埋点，未来工作） |
| Latency | runs.csv 里 `avg_model_latency_ms` + `avg_execution_latency_ms` |

---

## 6. CSV 数据库的版本兼容

`db/runs.csv` 和 `db/attempts.csv` 的字段是**统一的**（v2.0 和 v3.0 都用同一组字段）。

- 跑 v3.0 用例：所有字段都填
- 跑 v2.0 用例：v3.0 特有字段（`judge_*`、`style_intent_*`）填空

通过 `cli_args` JSON 字段里的 `legacy_suite: bool` 区分。

---

## 7. 团队过渡期沟通话术

如果有团队成员问"现在用 v2.0 还是 v3.0"：

> "**默认用 v3.0** 跑日常 benchmark。**发版前**额外跑一次 v2.0 legacy suite 防回归。**不要在 v3.0 用例里写 `expected_steps`**——那是旧 schema，会报错。"

---

## 8. 何时彻底废弃 v2.0

满足以下所有条件后可以考虑：

- v3.0 用例覆盖率达到 v2.0 的所有确定性场景（即 v2.0 单元测试集每条都有 v3.0 等价物）
- v3.0 evaluator 加入了"指定 bpy.ops 必须出现在 normalized_steps 里"的可选硬约束（这能精准对应步骤对比）
- 连续 6 个月 Pass-to-Pass = 100%，证明回归保护可以由 v3.0 接管
- 团队决议

**未达到时不要废弃**——红线指标的精准度比 schema 整洁度重要。

---

## 9. FAQ

**Q：v2.0 用例还能加新的吗？**
A：不能。v2.0 套件锁定为现有的 50-100 条。新用例一律写 v3.0。

**Q：我写了 v3.0 用例但忘了 `style_intent` 字段，会怎样？**
A：pydantic 会报 `ValidationError`：`Field required: style_intent`。schema 校验会强制你填。

**Q：能把 v2.0 的 `expected_steps` 转成 v3.0 的 hard_constraints 吗？**
A：不能直接转。`expected_steps` 是过程，hard_constraints 是结果——两者不是 1:1 映射。需要人工重新设计约束，详见 §4 Step 3。

**Q：v2.0 Chamfer Distance 在新系统还有用吗？**
A：仅在 L1 v2.0 套件里、且用例提供了 `target_mesh` 字段时计算。L2 完全不计算 Chamfer。

**Q：为什么不直接把 v2.0 的 expected_steps 当作 v3.0 的特殊约束？**
A：考虑过，但会污染 v3.0 schema 的纯净性。保持两套独立 schema、各管各的，长期维护成本更低。

---

**迁移文档结束。具体新用例编写请看 `TEST_CASE_AUTHORING.md`。**
