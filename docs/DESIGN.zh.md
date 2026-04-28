# Nalana 评测系统 V3.0 设计文档

**English version**: [`DESIGN.md`](DESIGN.md)

**版本**：3.0
**日期**：2026-04-25
**作者**：Nalana eval&testing team
**状态**：Active（已替代旧版 PDF "Model Performance Evaluation Standards Framework Proposal"）

---

## 0. 这份文档为谁而写

这份文档是新版 Nalana 评测系统的"宪法"。如果你是：

- **评测系统使用者**（开发者、QA）：你需要看完第 1、2、6、7 章，然后跳到 `USAGE_GUIDE.md`
- **测试用例编写者**（产品、设计师、QA）：你需要看完第 3、4 章，然后跳到 `TEST_CASE_AUTHORING.md`
- **架构维护者**（Nalana 工程团队）：通读全文，重点关注第 5、8、9 章
- **小白第一次接触评测系统**：从第 1 章 "为什么要重写" 开始读，每个章节都有"做什么 / 为什么 / 怎么做"三段式说明

**重要前提**：本文档假设读者了解 Blender 是什么、Python 是什么、JSON 是什么。不假设读者了解 LLM 评测、3D 几何拓扑、DPO。这些概念会在本文档里**第一次出现时解释**。

---

## 1. 为什么要重写

### 1.1 背景

Nalana 是一款基于 Blender 和 LLM 的 3D 模型生成软件——用户用自然语言描述（"画一个红色的苹果"），LLM 输出 JSON 形式的 Blender 操作指令，Blender 执行后产出 3D 模型。

旧版评测系统（详见旧 PDF "Model Performance Evaluation Standards Framework Proposal"）的核心思想是 **"用 ground truth 作为基准"**——把人类设计师在 Blender 里手工做出来的同款物体当作"标准答案"，然后看 LLM 的操作步骤和结果是否与之"复制"。

### 1.2 旧系统为什么不够用

旧系统假设"对同一个产品，正确答案只有一个"。这在传统软件工程里成立（输入 A 必然等于输出 B），但**在 AI 创作场景下根本不成立**：

- "画一个苹果" 可以是圆的、方的、卡通的、写实的——每种都可能是用户想要的
- "做一把椅子" 可以是四脚椅、三脚凳、扶手椅、办公椅——拓扑路径完全不同
- 即便是"创建一个立方体"，LLM 也可能用 `bpy.ops.mesh.primitive_cube_add()` 或先建一个面再挤出（`extrude`）——两种都对

旧系统的另外两个致命问题：

1. **不可规模化生产**。每个 ground truth 都需要人手在 Blender 里实做一遍并录制操作序列，新增 100 个用例约需 200 人时。
2. **抑制 LLM 真实能力**。当我们要求 LLM "复制"人类操作时，等于强制它放弃自身的最优解。GPT-5 也许有更聪明的拓扑路径，但因为不匹配 ground truth，就会被判 fail。

### 1.3 新系统的核心理念

把"对答案"换成 **"对约束"**：不再问"操作步骤是不是和人类一样"，而是问"输出的 3D 模型有没有满足必需的约束"——

- **硬约束（Hard Constraints）**：对象数量、类型、材质颜色、bounding box 尺寸、相对位置——必须满足，不满足判 fail。
- **拓扑约束（Topology Policy）**：是否流形（manifold）、四边面占比（quad ratio）、最大面数——衡量"工业级 mesh 质量"。
- **软约束（Soft Constraints）**：顶点数、面数等连续指标，加权打分，**不决定 pass/fail**，但贡献分数。
- **风格意图（Style Intent）+ LLM 评委**：当用户的意图涉及"像不像"、"美不美"等语义维度时，由 LLM 评委按用户意图标注的风格做软评分。

这套机制保留了"客观可机器评测"的特点（可全自动跑 1000 用例），同时承认 3D 创作的"答案不唯一"本质。

### 1.4 旧系统是否完全废弃？

**不**。某些操作有**唯一正确答案**——比如"撤销"只能是 `bpy.ops.ed.undo()`，"切换到编辑模式"只能是 `bpy.ops.object.mode_set(mode='EDIT')`。对于这类**确定性操作**，步骤对比仍是最精准的测试方式。

新系统的处理方式是**降级而非删除**：把 v2.0 的步骤对比降级为 **"L1 API 单元测试套件"**，仅覆盖 ~50–100 条确定性用例，作为防止回归的红线（详见第 2.1 节）。新版的 v3.0 约束测试是主 benchmark。

---

## 2. 三层评测架构

新系统从下到上分三层。每一层有独立的目标、用例集、指标，互不干扰：

```
┌─────────────────────────────────────────────────────────┐
│  L3：偏好对齐（Preference Alignment）— 长期工作         │
│  · LLM-as-Judge 语义评审（已实施）                       │
│  · 隐性反馈收集（保留/删除/编辑）→ DPO 训练数据（未来） │
│  · 人工 Elo 排名（冷启动阶段）                           │
├─────────────────────────────────────────────────────────┤
│  L2：约束验证（Constraint-Based Evaluation）— 主 benchmark │
│  · 硬约束：场景状态、对象属性、材质                       │
│  · 拓扑约束：manifold、quad ratio、面数上限               │
│  · 软约束：连续指标加权评分                               │
│  · 可规模化到 1000+ 用例，单次 run < 10 分钟               │
├─────────────────────────────────────────────────────────┤
│  L1：API 正确性（Deterministic Unit Tests）— 回归防护    │
│  · v2.0 legacy fixtures 改造为 50-100 条确定性用例        │
│  · 步骤对比 + Execution Success                          │
│  · Pass-to-Pass 红线                                     │
└─────────────────────────────────────────────────────────┘
```

### 2.1 L1：API 正确性（保留并限定范围）

**目标**：防止模型更新后在"基本 API 调用"上倒退。

**适用范围**：仅限**确定性操作**——参数和操作类型都有唯一正确答案的情况。

**用例数量**：50–100 条（不需要更多；这一层是回归保护，不是能力评估）。

**TaskFamily 限定**：

| TaskFamily | 示例 prompt | 唯一正确答案 |
|---|---|---|
| `scene_hygiene_safety` | "删除所有对象" | `bpy.ops.object.select_all() + bpy.ops.object.delete()` |
| `primitive_creation_default` | "添加一个默认立方体" | `bpy.ops.mesh.primitive_cube_add()` 不带任何参数 |
| `camera_assignment` | "设置摄像机到位置 (1, 2, 3)" | 参数完全来自用户指令 |
| `mode_switching` | "进入编辑模式" | `bpy.ops.object.mode_set(mode='EDIT')` |

**关键指标**：

- **Execution Success Rate**：生成的 JSON 是否能在 Blender 中无报错执行
- **Command Accuracy**：操作类型是否正确（例如 `ADD_MESH` 对，`SET_MATERIAL` 错）
- **Parameter Accuracy**：在操作类型正确的前提下，参数是否在 5% 容差内匹配
- **Pass-to-Pass**：模型更新后，之前通过的用例**必须仍然通过**——red line，不允许任何回归

### 2.2 L2：约束验证（核心、可规模化）

**目标**：验证 LLM 能否产生"可接受的"3D 输出，不限定操作路径。

**适用范围**：所有非确定性任务——即"答案有创造性空间"的任务。

**用例数量**：起步 200–300 条（手工 + 程序化扩展），目标 500–1000 条。

**用例 schema 总览**（详见 `TEST_CASE_AUTHORING.md`）：

```json
{
  "id": "CV-OBJ-042",
  "category": "Object Creation",
  "difficulty": "Medium",
  "task_family": "parameterized_primitive_creation",
  "prompt_variants": [
    "创建一个红色的球体，半径大约 2 米",
    "加一个大概 2 米半径的红球",
    "Add a red sphere, radius about 2 meters"
  ],
  "initial_scene": { "mode": "OBJECT" },
  "hard_constraints": {
    "mesh_object_count": { "minimum": 1 },
    "required_object_types": ["MESH"],
    "bounding_boxes": [
      { "target": "__scene__", "size_range": { "minimum": [3, 3, 3], "maximum": [5, 5, 5] }}
    ],
    "materials": [
      { "target": "*", "base_color": [1.0, 0.0, 0.0, 1.0], "tolerance": 0.2 }
    ]
  },
  "topology_policy": {
    "manifold_required": true,
    "quad_ratio_min": 0.0,
    "max_vertex_count": 10000
  },
  "soft_constraints": [
    { "name": "球体顶点数合理性", "metric": "total_vertices", "direction": "min", "target": 100, "weight": 0.5 }
  ],
  "style_intent": {
    "explicit": false,
    "concept": "sphere",
    "concept_aliases": ["ball", "球"],
    "acceptable_styles": ["geometric"]
  },
  "judge_policy": "score",
  "artifact_policy": {
    "require_screenshot": true,
    "write_scene_stats": true
  }
}
```

**关键设计原则：**

1. **多 prompt 变体**：每个用例必须有 3-5 个 `prompt_variants`，测试模型对不同措辞的鲁棒性
2. **约束应描述结果，而非过程**：错误是"用 `primitive_uv_sphere_add`"，正确是"场景中有一个 mesh 且 bounding box 在 [3,3,3]–[5,5,5] 内"
3. **约束应尽量宽松**：只排除明显错误，不变相指定唯一答案。半径要求 2 米的球，bbox 应该接受 [3,3,3]–[5,5,5]，而不是 [3.99,3.99,3.99]–[4.01,4.01,4.01]
4. **拓扑约束按用途分级**：

| 用途场景 | manifold | quad_ratio_min | 说明 |
|---|---|---|---|
| 概念展示/预览 | false | 0.0 | Nalana 当前阶段默认 |
| 游戏/实时渲染 | true | 0.7 | 标准游戏 mesh 要求 |
| 影视/VFX | true | 0.85 | 工业级，可细分 |
| 3D 打印 | true | 0.0 | 必须封闭，但三角面也 OK |

### 2.3 L3：偏好对齐

**目标**：评估"是否符合用户审美 / 期望"——这一层无法用纯几何约束捕捉。

**当前阶段实施的子模块：LLM-as-Judge**（详见第 4 章）。

**未来阶段**：

- 阶段 B：人工 Elo 排名（10–20 名美术评审员对同一 prompt 多输出做 pairwise 排序）
- 阶段 C：隐性反馈 DPO（产品端埋点采集 keep/delete/edit 行为，构建 `(prompt, chosen, rejected)` 三元组训练数据）

L3 的具体设计在第 4 章和第 9 章展开。

---

## 3. 关键概念词典

为避免团队沟通混乱，所有评测相关讨论使用以下统一术语：

| 术语 | 定义 |
|---|---|
| **Test case / 用例** | 一条 JSON，描述输入 prompt、初始场景、约束、风格意图等 |
| **Suite / 套件** | 一组用例的集合（如 `starter_v3.json`） |
| **Run / 单次运行** | 评测系统的一次完整执行，会产出一个 run folder |
| **Attempt / 尝试** | 同一个 case 的一次模型调用 + 一次 Blender 执行 + 一次评分。Pass@k 意味着每个 case 跑 k 次 attempt |
| **Hard constraint / 硬约束** | 决定 pass/fail 的约束。任何一个不满足，整个 case 判 fail |
| **Topology constraint / 拓扑约束** | 几何质量要求（manifold、quad ratio、面数）。同样决定 pass/fail |
| **Soft constraint / 软约束** | 加权评分的连续指标。**不决定 pass/fail**，只贡献分数 |
| **Style intent / 风格意图** | 用例作者声明的用户期望风格（cartoon/realistic/low-poly...），用于指导 LLM 评委 |
| **Judge / 判官** | LLM-as-Judge 模块，多模态 LLM 看截图给软评分 |
| **Pass@k** | 同一 case 跑 k 次 attempt，至少 1 次通过即视为 pass |
| **Pass-to-Pass** | 之前通过的用例在新模型版本下**必须仍然通过**（红线指标） |
| **Failure class** | 失败原因分类：PARSE_ERROR / EXECUTION_ERROR / CONSTRAINT_FAILED / TOPOLOGY_FAILED / SAFETY_BLOCKED 等 |
| **JSON dispatcher** | 评测系统内的 JSON 解析器，把 LLM 返回的 JSON 翻译成实际的 `bpy.ops.*` 调用 |
| **Worker pool / 工作池** | 多个常驻 Blender 进程，并行处理用例 |
| **Run folder** | 单次运行的输出目录（含 report.md / report.json / screenshots / scene_stats） |
| **CSV database** | 跨 run 持久化的结构化数据库（runs.csv + attempts.csv） |
| **Calibration set / 校准集** | 已知质量的参考图集合，用于检测 LLM 评委的系统性偏差 |
| **Honeypot / 诱饵用例** | 故意失败的 case，混入 run 中检测判官失灵 |

---

## 4. LLM-as-Judge：意图感知的语义评审

### 4.1 为什么需要它

约束验证（L2）能覆盖"API 掌握程度"和"基础几何常识"，但有两个盲区：

1. **概念匹配**：用户说"画苹果"，模型生成的 manifold 球体满足所有约束，但**它不像苹果**——没有苹果柄、没有底部凹陷
2. **审美**：同样满足约束的两个椅子，一个比例协调、一个比例失衡——约束无法分辨

L3 的 LLM-as-Judge 就是补这两个盲区。

### 4.2 核心挑战：尺子选错就会冤枉好人

LLM 评委有训练偏好。GPT-4o 见过的"专业 3D 苹果"大多是写实风格，所以它默认会**用写实标准评卡通**——结果卡通苹果在它眼里永远低分。

新版评测系统通过**四步走机制**确保判官对"风格中立"：

### 4.3 四步走机制详解

#### 步骤 1：用例作者显式声明 `style_intent`

```json
"style_intent": {
  "explicit": true,            // 用户是否明确指定了风格
  "style": "cartoon",          // 如果 explicit=true，必填
  "concept": "apple",          // 物体概念
  "concept_aliases": ["fruit"],// 接受的概念别名
  "acceptable_styles": ["cartoon", "stylized"]  // 如果 explicit=false，列出所有可接受的风格
}
```

**含义**：用例作者把"用户意图"从 LLM 的猜测变成了 schema 里的显式契约。判官不需要猜，只需按声明执行。

#### 步骤 2：两段式 prompt 强制"先识别再评判"

判官 prompt 的结构（详见 `prompts/judge_prompt.md` 完整版）：

```
你是一位 3D 建模评审。

【用户原始指令】
"画一个苹果"

【用例作者的意图声明】
- explicit: false
- concept: apple
- acceptable_styles: [cartoon, realistic, low-poly, stylized]

【你必须按以下步骤评分】

第 1 步（识别）：观察渲染图，识别建模者的意图：
   - detected_style: cartoon / realistic / low-poly / stylized / abstract
   - detected_concept: 这个物体表达的是什么概念？

第 2 步（验证对齐）：
   - 如果 explicit=true，对比 detected_style 和 用户指定的 style，不匹配则 style_alignment_pass=false
   - 如果 explicit=false，detected_style 在 acceptable_styles 里就视为合法
   - 概念检查：detected_concept 必须在 [concept] ∪ concept_aliases 内

第 3 步（按 detected_style 自身的标准评分）：
   ⚠️ 关键规则：必须按 detected_style 自身标准评分，不要跨风格比较
   - 评卡通 → 标准是"卡通建模该有的可爱、夸张、清晰边界"
   - 评写实 → 标准是"写实建模该有的细节、比例、材质"
   - 评 low-poly → 标准是"low-poly 该有的几何块面感、统一面数"
   不要因为是卡通就扣"不真实"分；不要因为是 low-poly 就扣"细节少"分。

返回严格 JSON（schema 见下）。
```

**返回 schema**：

```json
{
  "detected_style": "cartoon",
  "detected_concept": "apple",
  "style_alignment_pass": true,
  "concept_alignment_pass": true,
  "scores_within_detected_style": {
    "concept_recognizability": 4,    // 1-5，能认出是苹果吗
    "style_execution": 3,            // 1-5，作为卡通苹果做得好不好
    "geometric_quality": 3           // 1-5，拓扑、比例、完整度
  },
  "judged_under_standard": "cartoon",  // ⚠️ 强制声明用什么尺子评的，便于审计
  "reasoning": "...",                  // 简短理由
  "confidence": 0.8                    // 0-1，判官对自己评分的置信度
}
```

#### 步骤 3：校准集验证判官无系统性偏差

**做法**：

1. 准备 20–30 张"已知好的卡通建模"截图 + 20–30 张"已知好的写实建模"截图
2. 让判官按上述 prompt 给这批样本打分
3. **预期**：卡通组在卡通标准下的均分 ≈ 写实组在写实标准下的均分（误差 ±0.3 以内）
4. 如果两组均分有系统性偏差（如卡通组永远低 1 分），说明 prompt 还需调整或换判官模型

详见 `calibration/README.md`。

#### 步骤 4：方差检测 + 软信号包装 + 诱饵用例

- 每个用例让判官**评 3 次**（temperature=0.3，引入少量随机性测稳定性）
- 取**中位数**进 report，记录 `judge_stddev`
- 如果 `judge_stddev > 1.0`（5 分制），单独 flag "judge unstable"，提示人审重点看
- 判官分**永不参与硬 pass/fail**——只作为软信号，权重不超过总评分的 30%
- 每 10 个用例插入 1 个 honeypot（诱饵：空场景、跟 prompt 无关的物体）。如果判官给诱饵打了 4 分以上，整个 run 标记为 `judge_unreliable`

### 4.4 判官模型可配置

CLI 加 `--judge-model` flag：

| 默认 | GPT-4o（多模态稳定、JSON 模式可靠、$0.01/判断） |
|---|---|
| 备选 | Claude Sonnet 4.6、Gemini 2.5 Pro |
| 双判官模式 | `--judge-model gpt-4o,claude-sonnet-4` 两个独立评分取均值，2 倍成本，进一步降偏 |

**关键约束**：模型对比时必须用同一个判官，不然不公平。

### 4.5 成本与边界

- 单次判官调用约 $0.01（GPT-4o），200 用例 × 3 次评分 = ~$6/run
- CLI 加 `--judge-budget 5.0` 硬上限，超额跳过剩余调用、用 N/A 占位
- Cache：`hash(prompt + screenshot_pixels) → judge_result`，30 天 TTL，省 30–50% 成本

---

## 5. 执行架构

### 5.1 整体数据流

```
┌─────────────────┐
│  Test Suite     │  fixtures/starter_v3/*.json
│  (JSON 用例集)  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  CLI (nalana-eval)                      │
│  解析 --cases / --models / --pass-at-k  │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Harness（主调度器）                    │
│  · 加载 suite                           │
│  · 按比例采样 difficulty/length         │
│  · 分发到 ModelRunner + WorkerPool      │
└────────┬────────────────────────────────┘
         │
         ├──→ ┌─────────────────┐
         │    │  ModelRunner    │  调外部 LLM API
         │    │  (OpenAI/etc.)  │  返回 JSON ops
         │    └────────┬────────┘
         │             │
         │             ▼
         │    ┌─────────────────┐
         │    │  JSON 规范化    │  contracts.py
         │    │  + 安全 allow   │  拒绝危险操作
         │    └────────┬────────┘
         │             │
         ▼             ▼
┌─────────────────────────────────────────┐
│  WorkerPool（默认）或 SimpleRunner      │
│  · 给 Blender worker 发 case JSON       │
│  · subprocess + stdin/stdout 通信       │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Blender Worker (worker_loop.py)        │
│  · 在 Blender 内运行                    │
│  · reset_scene → 执行 ops → snapshot    │
│  · 渲染 PNG 截图（Workbench）           │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Evaluator（约束评估）                  │
│  · 硬约束 → pass/fail                   │
│  · 拓扑 → pass/fail                     │
│  · 软约束 → weighted score              │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Judge（LLM-as-Judge）                  │
│  · 接收 prompt + 截图 + style_intent    │
│  · 两段式评分 → 软信号                  │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Reporter                               │
│  ├── report.md / report.json            │
│  ├── screenshots/ + scene_stats/        │
│  └── 写入 db/runs.csv + db/attempts.csv │
└─────────────────────────────────────────┘
```

### 5.2 执行模式：Worker Pool（默认）vs Simple Mode

#### Worker Pool 模式（默认，速度优先）

启动时一次性开 N 个常驻 `blender --background --python worker_loop.py` 进程。worker_loop.py 进入循环：从 stdin 一行行读 case JSON，每跑完一个 case 把结果写到 stdout。harness 用 `subprocess.Popen` 维护 N 个进程的 pipe，case 之间用 `bpy.ops.wm.read_factory_settings(use_empty=True)` 清空场景。

- ✅ 1000 用例 5–10 分钟
- ⚠️ 进程可能内存涨/卡死。每 100 用例自动重启 worker（健康检查）
- 默认 N = `cpu_count() * 0.75`，CLI 可配 `--workers`

#### Simple Mode（CLI: `--simple-mode`）

每个 case：harness 启动一次 `blender --background --python single_run.py -- input.json output.json screenshot.png`，跑完 Blender 退出。下个 case 重启。

- ✅ 绝对干净环境，挂了不影响下一个
- ❌ 1000 用例 30–50 分钟
- 适合 CI、debug、第一次跑通验证

### 5.3 LLM 调用绕开 XML-RPC

**重要架构决策**：评测系统**完全不复用** Nalana 生产里的 XML-RPC（端口 8765）。

**原因**：
- 生产 RPC 的方法是 `enqueue_op_safe` 等，不是"接受 prompt 返回 JSON"
- 评测要支持任意第三方 LLM（GPT-5/Claude/Gemini），这些 LLM 不可能都包装成 Blender 插件
- 解耦 LLM 调用与 Blender 执行后，评测系统可独立运行，不需要先启动 Nalana 完整产品

**做法**：
- 评测系统的 `ModelRunner` 直接调外部 API（OpenAI SDK / Anthropic SDK / google.genai）
- 拿到 JSON 后通过 subprocess 直接发给 Blender worker（stdin/stdout，非 RPC）
- Blender worker 内部用评测系统自己的 dispatcher（`nalana_eval.dispatcher`）解析 JSON 并执行

### 5.4 截图渲染

**权威方案**：Workbench 引擎 + 程序化等距相机 + 800×600 PNG。

**为什么这套：**

| 选择 | 替代 | 不选的理由 |
|---|---|---|
| Workbench 引擎 | EEVEE / Cycles | EEVEE 需灯光配置、3-5 秒/帧；Cycles 5-30 秒/帧——1000 用例承受不起 |
| `bpy.ops.render.render(write_still=True)` | `bpy.ops.screen.screenshot()` | screenshot 在 `--background` 模式下完全不工作 |
| 程序化等距相机 | 复用场景已有相机 | 测试场景不一定有相机；即使有，未必对准生成物 |
| 800×600 PNG | 1920×1080 | 评测看大致形状/材质足够，省时省盘。CLI flag 可调 |

**核心代码**（`nalana_eval/screenshot.py` 实现）：

```python
def render_scene_to_png(output_path, resolution=(800, 600)):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = resolution[0]
    scene.render.resolution_y = resolution[1]
    scene.render.filepath = output_path
    scene.render.image_settings.file_format = 'PNG'

    # 程序化摆放相机：bbox 中心 + 等距视角，距离 = max_dim × 2.5
    # （详细实现见 nalana_eval/screenshot.py）
    place_camera_iso(scene)
    bpy.ops.render.render(write_still=True)
```

每个 attempt 出**两张图**：原图（800×600）+ 缩略图（512×384，给 markdown 嵌入用）。

---

## 6. CLI 与使用

### 6.1 主入口：`nalana-eval`

完整用法见 `USAGE_GUIDE.md`。最常见调用：

```bash
# 跑 200 个用例，对比 GPT-5 和 Claude Sonnet 4.6
nalana-eval \
    --cases 200 \
    --models gpt-5,claude-sonnet-4-6 \
    --difficulty-dist short:0.4,medium:0.4,long:0.2 \
    --pass-at-k 3 \
    --judge-model gpt-4o \
    --suite fixtures/starter_v3 \
    --workers 8

# 输出：artifacts/run_<timestamp>/
```

**API key 管理**：
- 从环境变量读取（`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`）
- 也支持 `--api-keys-file path/to/secrets.env`
- 永远不接受命令行明文（防止留在 shell history）

### 6.2 辅助 CLI

| 工具 | 用途 |
|---|---|
| `nalana-eval-history` | 查询 db/*.csv，出趋势/对比表 |
| `nalana-eval-review` | 收集 report.md 里的 HUMAN_REVIEW_BLOCK，回填到 attempts.csv |
| `nalana-eval-calibrate` | 跑判官校准集，输出 baseline 报告 |

---

## 7. 输出制品

### 7.1 单次 Run Folder 结构

```
artifacts/run_20260425_143022_<run_id_8>/
├── report.md                        ← 人类主报告
├── report.json                      ← 完整结构化数据
├── failures.jsonl                   ← 失败用例详细日志（每行一条）
├── screenshots/
│   ├── CV-OBJ-042_attempt_0.png         ← 原图 800×600
│   ├── CV-OBJ-042_attempt_0_thumb.png   ← 缩略图 512×384（md 嵌入用）
│   ├── CV-OBJ-042_attempt_1.png
│   └── ...
├── scene_stats/
│   ├── CV-OBJ-042_attempt_0.json    ← bmesh 统计、bbox、对象列表
│   └── ...
├── prompts_used.json                ← 这次 run 用了什么 system prompt
├── config.json                      ← 这次 run 的所有 CLI 参数
└── baseline_delta.json              ← 与上次同模型 run 的对比（如有）
```

### 7.2 跨 Run 持久化：CSV 数据库

`db/runs.csv` —— 每次 run 一行（多模型对比就是 N 行）。完整字段定义：

| 列名 | 说明 |
|---|---|
| run_id, timestamp_utc, model_id, prompt_template_version | 标识 |
| total_cases, total_attempts, difficulty_dist (JSON), category_dist (JSON) | 这次 run 的输入结构 |
| execution_success_rate, hard_pass_rate, topology_pass_rate, avg_soft_score, pass_at_1, pass_at_3 | L1/L2 主指标 |
| avg_judge_semantic, avg_judge_aesthetic, avg_judge_professional, judge_reliable | L3 软信号 + 判官健康 |
| avg_latency_ms, total_cost_usd | 成本 |
| report_md_path, report_json_path, git_commit, notes | 索引 + 审计 |

`db/attempts.csv` —— 每个 case 的每次 attempt 一行。完整字段见 `docs/CSV_SCHEMA.md`。

`db/judge_vs_human.csv` —— 长期积累"判官 vs 人审"差异，未来用于微调判官 prompt。

### 7.3 Markdown 报告样式

`report.md` 的内容大致结构：

```markdown
# Nalana Benchmark Run Report
**Run ID**: run_20260425_143022
**Models**: gpt-5, claude-sonnet-4-6
**Total Cases**: 200 | **Total Attempts**: 600 (Pass@3)

## Executive Summary
| Model | Hard Pass Rate | Topology Pass | Avg Soft | Pass@3 | Judge Avg |
|---|---|---|---|---|---|
| gpt-5 | 0.78 | 0.85 | 0.72 | 0.91 | 3.8/5 |
| claude-sonnet-4-6 | 0.74 | 0.83 | 0.69 | 0.88 | 3.9/5 |

## Breakdown by Category / Difficulty / Length
... (表格)

## Top Failure Reasons
1. CONSTRAINT_FAILED (23): bounding_box too small ...
2. TOPOLOGY_FAILED (12): non-manifold edges ...

## Sample Cases (失败用例 + 边界用例)

### ❌ FAIL: CV-OBJ-042 — "创建一个红色球体"
[![attempt 0](screenshots/CV-OBJ-042_attempt_0_thumb.png)](screenshots/CV-OBJ-042_attempt_0.png)

**Hard constraints**: ✗ material color (got grey, expected red)
**Topology**: ✓ manifold, quad_ratio = 0.0 (allowed)
**Judge** (under "geometric" standard): semantic=4 / style=3 / quality=3 / stddev=0.3

<!-- HUMAN_REVIEW_BLOCK:CV-OBJ-042:attempt_0
override: pending
corrected_semantic:
corrected_aesthetic:
corrected_professional:
reviewer:
note:
END_HUMAN_REVIEW_BLOCK -->
```

人审在编辑器里改 `HUMAN_REVIEW_BLOCK` 注释块（注：HTML 注释，不渲染），然后跑 `nalana-eval-review --collect path/to/report.md` 把反馈回流到 `db/attempts.csv` 的 `judge_human_override` 等列。

---

## 8. 指标体系

### 8.1 L1 指标（API 单元测试）

| 指标 | 计算 | 红线 |
|---|---|---|
| Execution Success Rate | 成功执行 / 总用例 | ≥ 95% |
| Command Accuracy | 操作类型正确数 / 总操作数 | ≥ 90% |
| Parameter Accuracy | 参数匹配分 / 总操作数 | ≥ 85% |
| **Pass-to-Pass Rate** | 更新后仍通过的旧用例 / 旧用例总数 | **= 100%（红线）** |

### 8.2 L2 指标（约束验证）

| 指标 | 计算 | 当前目标 |
|---|---|---|
| Hard Pass Rate | 所有硬约束通过的 case / 总 case | ≥ 70% |
| Topology Pass Rate | 拓扑约束通过的 case / 总 case | ≥ 80% |
| Avg Soft Score | 软约束加权分均值 | ≥ 0.6 |
| Pass@1 | 第 0 次 attempt 通过的 case 比例 | ≥ 60% |
| Pass@3 | 3 次 attempt 中至少 1 次通过 | ≥ 85% |

### 8.3 L3 指标（偏好对齐）

| 指标 | 计算 | 当前目标 |
|---|---|---|
| Judge Semantic Avg | 判官语义匹配分均值（5 分制） | ≥ 3.5 |
| Judge Aesthetic Avg | 判官美观分均值 | ≥ 3.0 |
| Judge Professional Avg | 判官专业度分均值 | ≥ 3.0 |
| Judge Stability | 1 - (stddev > 1.0 的用例占比) | ≥ 0.9 |
| Judge Honeypot Catch Rate | 诱饵被打 ≤ 2 分的比例 | ≥ 0.95 |
| Calibration Drift | 判官在校准集上的偏差（详见 calibration/） | ≤ 0.3 |

### 8.4 模型对比基线

沿用旧方案的"以 Gemini Pro 3 作为基线"思路，但改为：以**最新一次 GPT-5 run**作为流动基线。每次新模型 run 自动与最近一次 baseline run 对比，输出 `baseline_delta.json`。

**红线规则**（模型不能发布的条件）：
- Pass-to-Pass Rate < 100%
- Execution Success Rate 下降 > 2%
- Hard Pass Rate 下降 > 5%
- Topology Pass Rate 下降 > 5%

### 8.5 工程层面的 deterministic 测试（不与模型 benchmark 混淆）

以下是评测系统**自身代码**的单元/集成测试，留在 repo 的 `tests/`，不进 benchmark 报告：

- `test_schema.py`：v3.0 schema 校验
- `test_contracts.py`：JSON 规范化、allowlist、参数边界
- `test_dispatcher.py`：JSON → bpy.ops 的翻译正确性
- `test_evaluator.py`：约束计算正确性
- `test_judge.py`：判官 prompt 构造、JSON 解析
- `test_csv_db.py`：CSV 写入读出、人审回流

这些测试用 pytest 跑，与 `nalana-eval` benchmark 解耦。

---

## 9. 偏好对齐路线图

### Phase 1：现在（V3.0 发布即包含）

✅ LLM-as-Judge（意图感知、四步走、校准集）
✅ Honeypot 诱饵
✅ Judge 缓存 + 预算上限
✅ 人审反馈通道（HUMAN_REVIEW_BLOCK → CSV）
✅ judge_vs_human.csv 长期积累

### Phase 2：人工 Elo 排名（建议 2-4 周后启动）

招募 10-20 名美术评审员，每人对同一 prompt 的 3 个不同模型输出做 pairwise 排序。50 个 prompt × 5 判断 = 250 条数据即可建立初始 Elo 基线。

工具：`nalana-eval-elo`（Phase 2 实现）

### Phase 3：隐性反馈采集（依赖产品端埋点）

在 Nalana Blender 插件中埋入：
- `kept` / `deleted` / `edited` / `final_selected` 信号
- `time_to_first_edit` / `edit_distance`
- 多个候选时的最终选择

数据采集 → 存储到 db/preference_events.csv → 导出为 DPO 训练数据。

### Phase 4：DPO 训练（需 2000+ preference pair）

构建 `(prompt, chosen, rejected)` 三元组：
- chosen = `final_selected: true` 或 `kept: true && edit_distance < threshold`
- rejected = `deleted: true` 或 `edit_distance > threshold`
- 排除归因不清晰数据（如 5 秒内连续删除全部候选）

第一轮 DPO → A/B 测试新旧模型 → 迭代。

---

## 10. 与旧 PDF 系统的映射

| 旧 PDF 概念 | 新系统对应 | 变化 |
|---|---|---|
| Ground-truth sequence | L1 legacy fixtures（限定确定性操作） | 范围大幅缩小，仅保留作回归 |
| Command Accuracy | L1 metric（仅限确定性用例） | 保留但仅用于 L1 |
| Parameter Accuracy | L1 metric | 同上 |
| Geometric Accuracy（Chamfer Distance） | L1 仅在有参考网格时计算 | L2 完全不用 |
| Execution Success | 所有层级的基础门槛 | 升级 |
| Quad Ratio / Manifold | L2 TopologyPolicy | 从 quality_signals 升级为正式约束 |
| Multimodal Reasoning Score | L2 截图采集 + L3 LLM-as-Judge | 拆分 |
| Productions Accepted Rate | L3 Phase 3 隐性反馈（未来） | 路线图 |
| Resolution Rate (SWE-bench) | L2 Hard Pass Rate | 概念对齐，实现重写 |
| Pass@k | L2 Pass@k via prompt_variants 多次 attempt | 保留 |
| Pass-to-Pass | L1 红线 | 保留 |

---

## 11. FAQ

**Q：旧 v2.0 fixtures 还能用吗？**
能。通过 `--legacy-suite` flag 指向 v2.0 fixtures 跑 L1 单元测试。但默认 benchmark 不再用它们。

**Q：如果一个 prompt 高度模糊（"做个好看的东西"），约束怎么写？**
硬约束只保留最基本的（`mesh_object_count >= 1`、`manifold_required: false`），把评估交给 LLM-as-Judge。

**Q：软约束权重怎么定？**
起步阶段所有权重 = 1.0（等权）。随着 Elo 数据积累，反推最优权重——美术总偏好 quad ratio 高的就提升其权重。

**Q：判官给我打了不公平的分怎么办？**
在 report.md 的 `HUMAN_REVIEW_BLOCK` 里改 override 字段，跑 `nalana-eval-review --collect`。久了会积累 `judge_vs_human.csv`，反过来用于微调判官 prompt。

**Q：Chamfer Distance 完全没了？**
仅保留在 L1 有明确参考网格的确定性用例中。L2 完全不用。

**Q：能不能不用 LLM-as-Judge？**
能。CLI 加 `--no-judge` 直接跳过 L3。但建议至少在正式 benchmark 时开，因为约束测不了语义。

**Q：模型测试时不同模型用什么 system prompt？**
默认所有模型用同一个 `eval_default.md`（保证公平比较）。如需对比"加了 Nalana 业务 prompt 后的差异"，用 `--system-prompt nalana-prod`。

**Q：1000 用例真能 10 分钟跑完？**
取决于硬件。8 个 worker、Workbench 渲染、平均 3 ops/case 的情况下，约 5-8 分钟。CPU 越多越快。

---

## 附录 A：依赖与环境要求

- Python 3.10+
- Blender 4.0+ （`blender` 命令在 PATH 中，或通过 `BLENDER_BIN` 环境变量指定）
- pip 依赖见 `requirements.txt`（pydantic、openai、anthropic、google-genai、Pillow）
- 操作系统：macOS / Linux / Windows（已在 macOS 测试）

## 附录 B：贡献指南

新增用例 → `fixtures/starter_v3/<category>.json`，提 PR 时跑 `pytest tests/test_schema.py` 确保 schema 校验通过。

新增 task family → 同时更新 `nalana_eval/schema.py` 的 `TaskFamily` enum、`TEST_CASE_AUTHORING.md` 的模板表、`prompts/eval_default.md` 的 contract 描述。

判官 prompt 改动 → 必须重跑校准集，对比 baseline 偏移。

---

**文档结束。完整使用细节见 `USAGE_GUIDE.md`，用例编写细节见 `TEST_CASE_AUTHORING.md`。**
