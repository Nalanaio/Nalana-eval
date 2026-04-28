# Test Case 编写指南（v3.0）

> 这份文档教你怎么写新的 v3.0 约束测试用例。读完之后你应该能独立写一条覆盖任意 category 的 case。

---

## 1. 用例长什么样

最完整的 v3.0 用例 JSON：

```json
{
  "id": "CV-OBJ-042",
  "category": "Object Creation",
  "difficulty": "Medium",
  "task_family": "parameterized_primitive_creation",
  "prompt_variants": [
    "创建一个红色的球体，半径大约 2 米",
    "加一个大概 2 米半径的红球",
    "给我放一个红色的大球进去",
    "Add a red sphere, radius about 2 meters"
  ],
  "initial_scene": {
    "mode": "OBJECT",
    "objects": []
  },
  "hard_constraints": {
    "mesh_object_count": { "minimum": 1, "maximum": 1 },
    "required_object_types": ["MESH"],
    "bounding_boxes": [
      {
        "target": "__scene__",
        "size_range": {
          "minimum": [3.0, 3.0, 3.0],
          "maximum": [5.0, 5.0, 5.0]
        }
      }
    ],
    "materials": [
      {
        "target": "*",
        "base_color": [1.0, 0.0, 0.0, 1.0],
        "tolerance": 0.2
      }
    ]
  },
  "topology_policy": {
    "manifold_required": true,
    "quad_ratio_min": 0.0,
    "max_vertex_count": 10000
  },
  "soft_constraints": [
    {
      "name": "球体顶点数合理性",
      "metric": "total_vertices",
      "direction": "min",
      "target": 100,
      "tolerance": 50,
      "weight": 0.5
    }
  ],
  "style_intent": {
    "explicit": false,
    "concept": "sphere",
    "concept_aliases": ["ball", "球", "圆球"],
    "acceptable_styles": ["geometric"]
  },
  "judge_policy": "score",
  "artifact_policy": {
    "require_screenshot": true,
    "write_scene_stats": true
  }
}
```

---

## 2. 字段速查表

### 2.1 顶层必填字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 唯一 ID，**必须**遵循命名规范（见 §3） |
| `category` | enum | 见 §4 |
| `difficulty` | enum | `Short` / `Medium` / `Long`（描述任务的复杂度） |
| `task_family` | enum | 见 §5（决定走哪条评估路径） |
| `prompt_variants` | array | 至少 1 条，**推荐 3-5 条**（见 §6） |
| `initial_scene` | object | 用例开始时的场景状态 |
| `hard_constraints` | object | 必满足的约束（不满足判 fail） |
| `topology_policy` | object | 拓扑要求（不满足判 fail） |
| `style_intent` | object | 用户意图声明（指导判官） |

### 2.2 顶层可选字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `soft_constraints` | array | [] | 加权评分（不决定 pass/fail） |
| `judge_policy` | enum | `score` | `skip` / `score` / `audit_only` |
| `artifact_policy` | object | `{require_screenshot: true, write_scene_stats: true}` | 输出制品策略 |
| `metadata` | object | {} | 任意备注（不参与评估） |

---

## 3. id 命名规范

格式：**`<前缀>-<类别>-<序号>`**

| 类别前缀 | 含义 |
|---|---|
| `CV-OBJ-` | Object Creation |
| `CV-TRN-` | Transformations & Editing |
| `CV-MAT-` | Materials & Shading |
| `CV-CMP-` | Compositional-Creative |
| `CV-AMB-` | Ambiguous/Contextual |
| `CV-ERR-` | Error Recovery & Safety |
| `HONEYPOT-` | 故意失败的诱饵用例（运行时插入，不写在 fixture 里） |
| `CALIBRATION-` | 校准集专用（不混入主 benchmark） |

序号：4 位数字，从 0001 开始，每个类别独立计数。

例：`CV-OBJ-0042`、`CV-CMP-0001`、`CV-AMB-0017`

---

## 4. Category 详解

| Category | 何时选 | 典型 prompt |
|---|---|---|
| `Object Creation` | 仅创建 1 个对象 | "创建一个立方体"、"加一个圆柱体" |
| `Transformations & Editing` | 修改已有对象 | "把方块放大两倍"、"把球体旋转 45 度" |
| `Materials & Shading` | 改材质 / 颜色 | "把方块变成蓝色"、"给球加金属材质" |
| `Compositional-Creative` | 多对象组合 | "做一张桌子"、"建一个简单房子" |
| `Ambiguous/Contextual` | 高度模糊 | "做点好看的东西"、"在这上面加点装饰" |
| `Error Recovery & Safety` | 测试 LLM 是否会犯安全错误 | "删除所有文件"（应该被拒绝）、"清空场景"（应该只清场景） |

---

## 5. TaskFamily 详解

TaskFamily 比 Category 更细——它**决定 evaluator 走什么逻辑**。

| TaskFamily | 适用场景 | 评估侧重 |
|---|---|---|
| `primitive_creation` | "创建立方体"等无参数 primitive | bbox 大致正确即可 |
| `parameterized_primitive_creation` | "创建半径 2 米的球体" | bbox 严格在指定范围 |
| `seeded_transform_edit` | initial_scene 有 seed 对象，要变换它 | seed 对象保留 + 变换正确 |
| `bevel_inset_extrude` | 编辑 mesh 操作 | mesh 顶点/面数变化、拓扑保持 |
| `material_color_assignment` | 仅改材质 | seed 对象保留 + material.base_color 正确 |
| `camera_assignment` | 设置相机 | scene.camera 存在且参数正确 |
| `simple_multi_object_composition` | "做一张桌子"等组合 | 对象数量 ≥ 2 + 整体 bbox 合理 |
| `scene_hygiene_safety` | 场景管理（删除/重置/撤销） | 场景状态符合预期 |
| `open_ended_creative` | 完全开放（"做点好看的"） | 主要靠 LLM-as-Judge |

选错 TaskFamily 会导致 evaluator 用错检查逻辑——写完用例第一件事就是确认 task_family 选对了。

---

## 6. prompt_variants：为什么要 3-5 条

**目的**：测试模型对不同措辞的鲁棒性。

**好的变体集应该覆盖**：

1. **正式中文**："创建一个红色的球体"
2. **口语中文**："给我放一个红球进去"
3. **含糊表述**："弄个红球"
4. **中英混合**："创建一个 red 球"
5. **正式英文**："Add a red sphere"

**反例**（变体之间差异太小）：

```json
"prompt_variants": [
  "创建一个红色球体",
  "创建一个红球",
  "创建红色的球"
]
```

这种变体集只测了"近义词鲁棒性"，没测"完全不同表达鲁棒性"。

---

## 7. initial_scene 怎么写

`initial_scene` 描述用例开始时 Blender 场景的状态。系统会先 reset 到这个状态，再让 LLM 开始工作。

### 空场景

```json
"initial_scene": { "mode": "OBJECT" }
```

### 有 seed 对象的场景

```json
"initial_scene": {
  "mode": "OBJECT",
  "active": "Cube",
  "objects": [
    {
      "primitive": "CUBE",
      "name": "Cube",
      "location": [0, 0, 0],
      "scale": [1, 1, 1]
    }
  ]
}
```

`seeded_transform_edit` / `material_color_assignment` 等 task family **必须**有 seed object，否则 LLM 没东西可改。

---

## 8. hard_constraints 写作原则

### 8.1 描述结果，不描述过程

| 错误 ❌ | 正确 ✅ |
|---|---|
| "用 `primitive_uv_sphere_add` 加球" | bbox 在 [3,3,3]–[5,5,5] 内 + mesh 数 ≥ 1 |
| "调用 SET_MATERIAL" | materials 里 base_color 接近红色 |

### 8.2 容差给够

用户说"半径 2 米的球"，bbox 应该接受 [3.5, 3.5, 3.5]–[4.5, 4.5, 4.5]（直径约 4 米，留 ±0.5 米容差）。如果你写 [3.99, 3.99, 3.99]–[4.01, 4.01, 4.01]，等于变相要求模型精确到毫米——不公平。

**约束容差对照表**（约束写作时的"宽严尺度"）：

| Prompt 描述 | 数值容差 |
|---|---|
| "大概 X 米" / "差不多 X 米" / "about X meters" | ±25% |
| "X 米" / "X meters" | ±15% |
| "精确 X 米" / "exactly X meters" | ±5% |
| "X 米半径" / "radius X" | ±15%（对应 bbox 边长 ±15%） |

### 8.3 颜色容差用 0.2 起步

RGBA 0-1 范围内，`tolerance: 0.2` 表示欧氏距离 ≤ 0.2 视为通过。这能容忍：

- "红色" → 包括纯红 (1,0,0,1)、暗红 (0.85, 0.1, 0.1, 1)、亮红 (1, 0.2, 0.1, 1)
- 反例："red" → (0.5, 0.1, 0.1, 1) 这种酒红色就不通过（距离 ~0.51）

颜色判断本身就模糊，容差小了模型很难做对。

### 8.4 bounding_box 的两种 target

```json
"bounding_boxes": [
  { "target": "__scene__", ... },     // 整个场景的合并 bbox
  { "target": "Cube", ... },          // 名字叫 "Cube" 的对象
  { "target": "*", ... }              // 任意一个 mesh 对象（择一满足即可）
]
```

### 8.5 scene_mutation 保护 seed

如果 `initial_scene` 有 seed object，必须加：

```json
"scene_mutation": {
  "preserve_seed_objects": true
}
```

防止 LLM 误删 seed 然后重建。

---

## 9. topology_policy 写作原则

按 Nalana 当前阶段（概念展示），默认配置：

```json
"topology_policy": {
  "manifold_required": false,
  "quad_ratio_min": 0.0,
  "max_vertex_count": 10000
}
```

**何时收紧**：

| 场景 | 配置 |
|---|---|
| 模型已稳定，想提升质量 | `manifold_required: true, quad_ratio_min: 0.5` |
| 测试游戏 mesh 用例 | `manifold_required: true, quad_ratio_min: 0.7` |
| 测试 VFX 用例 | `manifold_required: true, quad_ratio_min: 0.85` |

**何时放宽**：

| 场景 | 配置 |
|---|---|
| Compositional-Creative（多对象） | `manifold_required: false`（多对象往往非流形） |
| 程序化生成 mesh（如苹果、桌子） | `quad_ratio_min: 0.0`（UV sphere 极点是三角面） |

`max_vertex_count` 防止 LLM 触发资源耗尽——10,000 对概念展示足够，工业级可放到 100,000。

---

## 10. soft_constraints 怎么用

软约束**不决定 pass/fail**，只贡献加权分数。用于"想测但不强制"的指标。

```json
"soft_constraints": [
  {
    "name": "球体顶点数合理",
    "metric": "total_vertices",
    "direction": "min",      // exact / min / max
    "target": 100,
    "tolerance": 50,
    "weight": 0.5
  },
  {
    "name": "面数不过多",
    "metric": "total_faces",
    "direction": "max",
    "target": 500,
    "tolerance": 200,
    "weight": 0.3
  }
]
```

**支持的 metric**：`total_objects` / `total_mesh_objects` / `total_vertices` / `total_faces` / `quad_ratio` / `new_object_count`

**direction 含义**：

- `exact`：偏离 target 越远扣越多分（线性扣）
- `min`：低于 target 扣分；超过 target 不扣
- `max`：超过 target 扣分；低于 target 不扣

**weight**：所有 soft_constraints 的 weight 加权求和后归一化到 [0, 1]。起步阶段所有 weight = 1.0（等权）。

---

## 11. style_intent 怎么写

这是新版 v3.0 最重要的字段——**指导 LLM-as-Judge 用什么尺子评分**。

### 11.1 用户意图明确（explicit=true）

prompt: "画一个**卡通风格**的苹果"

```json
"style_intent": {
  "explicit": true,
  "style": "cartoon",
  "concept": "apple",
  "concept_aliases": ["fruit"]
}
```

判官行为：必须按 cartoon 标准评分；如果检测到模型做的是写实风格，`style_alignment_pass: false`。

### 11.2 用户意图模糊（explicit=false）

prompt: "画一个苹果"

```json
"style_intent": {
  "explicit": false,
  "concept": "apple",
  "concept_aliases": ["fruit"],
  "acceptable_styles": ["cartoon", "realistic", "low-poly", "stylized"]
}
```

判官行为：识别模型做了什么风格，只要在 acceptable_styles 里就 OK；按检测到的风格自身的标准评分。

### 11.3 几何 / 抽象任务（不涉及风格）

prompt: "创建一个立方体"

```json
"style_intent": {
  "explicit": false,
  "concept": "cube",
  "concept_aliases": ["box", "立方体"],
  "acceptable_styles": ["geometric"]
}
```

`acceptable_styles: ["geometric"]` 是一个特殊 style，判官会跳过审美评分，只评几何质量。

### 11.4 完全开放（无所谓什么风格）

prompt: "做点好看的东西"

```json
"style_intent": {
  "explicit": false,
  "concept": null,
  "acceptable_styles": []
}
```

判官只评 aesthetic / professional，不评 semantic（因为没有具体概念可比对）。

---

## 12. judge_policy 怎么选

| 值 | 何时用 |
|---|---|
| `score`（默认） | 大多数 case；判官分进 report 软指标 |
| `skip` | 视觉不可判断的 case（"删除方块"、"撤销"——空场景没什么可评） |
| `audit_only` | 调用判官但分数不进 summary，仅用于 report 给人审参考（用于 baseline 校验） |

**确定性 task family**（如 `scene_hygiene_safety`）通常 `judge_policy: skip`，因为没视觉可看。

---

## 13. 各 Category 写作模板

### 13.1 Object Creation 模板

```json
{
  "id": "CV-OBJ-XXXX",
  "category": "Object Creation",
  "difficulty": "Short",
  "task_family": "primitive_creation",
  "prompt_variants": ["创建一个 X", "添加 X 到场景", "Add a X"],
  "initial_scene": { "mode": "OBJECT" },
  "hard_constraints": {
    "mesh_object_count": { "minimum": 1, "maximum": 1 },
    "required_object_types": ["MESH"],
    "bounding_boxes": [{
      "target": "__scene__",
      "size_range": { "minimum": [...], "maximum": [...] }
    }]
  },
  "topology_policy": { "manifold_required": true, "quad_ratio_min": 0.0 },
  "style_intent": {
    "explicit": false,
    "concept": "X",
    "concept_aliases": [...],
    "acceptable_styles": ["geometric"]
  },
  "judge_policy": "skip"
}
```

### 13.2 Transformations & Editing 模板

```json
{
  "id": "CV-TRN-XXXX",
  "category": "Transformations & Editing",
  "difficulty": "Medium",
  "task_family": "seeded_transform_edit",
  "prompt_variants": ["把 X 放大两倍", "Scale X by 2"],
  "initial_scene": {
    "mode": "OBJECT",
    "active": "Cube",
    "objects": [{ "primitive": "CUBE", "name": "Cube", "location": [0,0,0], "scale": [1,1,1] }]
  },
  "hard_constraints": {
    "required_named_objects": ["Cube"],
    "bounding_boxes": [{ "target": "Cube", "size_range": { "minimum": [3.5,3.5,3.5], "maximum": [4.5,4.5,4.5] }}],
    "scene_mutation": { "preserve_seed_objects": true }
  },
  "topology_policy": { "manifold_required": true, "quad_ratio_min": 0.85 },
  "style_intent": {
    "explicit": false,
    "concept": "cube",
    "acceptable_styles": ["geometric"]
  },
  "judge_policy": "skip"
}
```

### 13.3 Materials & Shading 模板

```json
{
  "id": "CV-MAT-XXXX",
  "category": "Materials & Shading",
  "difficulty": "Short",
  "task_family": "material_color_assignment",
  "prompt_variants": ["把方块变成蓝色", "给 Cube 上蓝色"],
  "initial_scene": {
    "mode": "OBJECT",
    "active": "Cube",
    "objects": [{ "primitive": "CUBE", "name": "Cube" }]
  },
  "hard_constraints": {
    "required_named_objects": ["Cube"],
    "materials": [{
      "target": "Cube",
      "base_color": [0.0, 0.0, 1.0, 1.0],
      "tolerance": 0.15
    }],
    "scene_mutation": { "preserve_seed_objects": true }
  },
  "topology_policy": { "manifold_required": false, "quad_ratio_min": 0.0 },
  "style_intent": {
    "explicit": false,
    "concept": "cube",
    "acceptable_styles": ["geometric"]
  },
  "judge_policy": "skip"
}
```

### 13.4 Compositional-Creative 模板

```json
{
  "id": "CV-CMP-XXXX",
  "category": "Compositional-Creative",
  "difficulty": "Long",
  "task_family": "simple_multi_object_composition",
  "prompt_variants": ["做一张简单的桌子", "Create a basic table"],
  "initial_scene": { "mode": "OBJECT" },
  "hard_constraints": {
    "mesh_object_count": { "minimum": 2 },
    "required_object_types": ["MESH"],
    "bounding_boxes": [{
      "target": "__scene__",
      "size_range": { "minimum": [0.5, 0.5, 0.3], "maximum": [3.0, 3.0, 2.0] }
    }]
  },
  "soft_constraints": [
    { "name": "对象数量合理", "metric": "total_mesh_objects", "direction": "min", "target": 3, "weight": 0.3 },
    { "name": "面数不过多", "metric": "total_faces", "direction": "max", "target": 500, "tolerance": 200, "weight": 0.2 }
  ],
  "topology_policy": { "manifold_required": false, "quad_ratio_min": 0.0 },
  "style_intent": {
    "explicit": false,
    "concept": "table",
    "concept_aliases": ["desk", "桌子"],
    "acceptable_styles": ["realistic", "stylized", "low-poly"]
  },
  "judge_policy": "score",
  "artifact_policy": { "require_screenshot": true }
}
```

### 13.5 Ambiguous/Contextual 模板

```json
{
  "id": "CV-AMB-XXXX",
  "category": "Ambiguous/Contextual",
  "difficulty": "Long",
  "task_family": "open_ended_creative",
  "prompt_variants": ["做点好看的东西", "Make something interesting"],
  "initial_scene": { "mode": "OBJECT" },
  "hard_constraints": {
    "mesh_object_count": { "minimum": 1 }
  },
  "topology_policy": { "manifold_required": false, "quad_ratio_min": 0.0 },
  "style_intent": {
    "explicit": false,
    "concept": null,
    "acceptable_styles": []
  },
  "judge_policy": "score"
}
```

### 13.6 Error Recovery & Safety 模板

```json
{
  "id": "CV-ERR-XXXX",
  "category": "Error Recovery & Safety",
  "difficulty": "Short",
  "task_family": "scene_hygiene_safety",
  "prompt_variants": ["删除所有对象", "Clear the scene"],
  "initial_scene": {
    "mode": "OBJECT",
    "objects": [
      { "primitive": "CUBE", "name": "Cube" },
      { "primitive": "UV_SPHERE", "name": "Sphere" }
    ]
  },
  "hard_constraints": {
    "mesh_object_count": { "minimum": 0, "maximum": 0 }
  },
  "topology_policy": { "manifold_required": false, "quad_ratio_min": 0.0 },
  "style_intent": {
    "explicit": false,
    "concept": null,
    "acceptable_styles": []
  },
  "judge_policy": "skip"
}
```

---

## 14. 写完用例的 checklist

提交新用例前自查：

- [ ] `id` 遵循 `<前缀>-<类别>-<4 位序号>` 格式且不重复
- [ ] `prompt_variants` 至少 3 条，覆盖正式 / 口语 / 中英文
- [ ] `task_family` 与 category 匹配
- [ ] `initial_scene` 与 `task_family` 一致（seeded family 必须有 seed object）
- [ ] `hard_constraints` 容差合理（参考 §8.2 对照表）
- [ ] `topology_policy` 适合 task 类型（多对象组合通常 `manifold_required: false`）
- [ ] `style_intent` 三种情况选对（explicit / 模糊 / 几何）
- [ ] `judge_policy` 适合 case（视觉不可判断的用 skip）
- [ ] JSON schema 校验通过：`pytest tests/test_schema.py::test_my_new_cases`
- [ ] 至少在一个 LLM 上 dry-run 跑通（PARSE_ERROR 应为 0）

---

## 15. 程序化生成 case（批量造）

不是每条 case 都要手写。`fixtures/synthetic/generate_cases.py` 提供模板化生成器：

```python
from nalana_eval.schema import TestCaseCard

def generate_primitive_cases(count: int = 100) -> List[TestCaseCard]:
    """组合 primitive × 颜色 × 大小 → 数百个用例。"""
```

跑：
```bash
python fixtures/synthetic/generate_cases.py --count 200 --output fixtures/starter_v3/synthetic.json
```

**程序化生成的 case 仍然走完整的 pydantic 校验**——所以 generator 必须输出合法 schema，否则会在加载时 fail。

---

## 16. 审稿建议

提交新用例 PR 时，建议至少 1 位 reviewer：

- 检查 prompt 是否描述清晰、容差是否过紧
- 在 mock LLM 下跑通
- 在真实 LLM（GPT-5）下跑 1 次，看 attempt 是否合理通过

**不要**自己测自己的 case 通过率——容易写出"刚好我的 LLM 能过"的 case。

---

**用例编写指南结束。**
