# Nalana 评测系统 V3.0

> 一套以"约束验证 + 偏好对齐"为核心的 LLM × Blender 3D 建模评测系统。

**English version**: [`README.md`](README.md)

---

## 5 分钟读懂这是什么

Nalana 是一款基于 LLM 和 Blender 的 3D 模型生成软件——用户用自然语言描述（"画一个红色的苹果"），LLM 输出 JSON 格式的 Blender 操作指令，Blender 执行后产出 3D 模型。

**这套评测系统**用于回答两个问题：

1. **客观能力**：哪个 LLM（GPT-5 / Claude / Gemini …）最适合做 Nalana 的后端？
2. **主观满意度**：模型的输出是不是用户审美能接受的？

**它不是什么**：不是 Nalana 产品本身。是一个**独立运行**的测试工具，不需要你先启动 Nalana 完整产品。

---

## 用一张图理解整个系统

```
你写好的测试用例 (JSON, 200-300 条)
        ↓
nalana-eval CLI
   --cases 200 --models gpt-5,claude-sonnet-4-6 --pass-at-k 3
        ↓
对每个 case：
   1) LLM 收到 prompt → 输出 JSON ops
   2) Blender 执行 JSON ops → 产生 3D 模型
   3) 截图（PNG）+ 抓取场景统计
   4) 三层评估：
      L1 API 单元测试（确定性操作的步骤对比）
      L2 约束验证（硬约束 + 拓扑 + 软约束）
      L3 LLM-as-Judge（语义/审美/专业度）
        ↓
输出：
   artifacts/run_<timestamp>/
   ├── report.md                ← 人审看这个
   ├── report.json              ← 机器读这个
   ├── screenshots/             ← 每个 attempt 一张 PNG
   └── scene_stats/             ← 每个 attempt 一个几何 JSON

   db/runs.csv                  ← 跨 run 的历史汇总
   db/attempts.csv              ← 每个 attempt 的细粒度数据
```

---

## 快速开始（小白指南）

### 步骤 1：装依赖

```bash
cd /Users/ianian/Nalana-eval
pip install -r requirements.txt

# 装 Blender 4.0+（如果还没装）
# macOS: brew install --cask blender
# Linux: 从 https://www.blender.org/download/ 下载
# 验证：blender --version
```

### 步骤 2：配 API key

```bash
# 推荐：写到 .env 文件（已在 .gitignore，不会进 git）
cat > .env <<EOF
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
EOF
```

### 步骤 3：跑第一次（10 个 case 的 smoke test）

```bash
python -m nalana_eval.cli \
    --cases 10 \
    --models gpt-5 \
    --suite fixtures/starter_v3 \
    --simple-mode      # 第一次先用 simple-mode 确认环境 OK
```

输出在 `artifacts/run_<timestamp>/`，打开 `report.md` 看结果。

### 步骤 4：正式跑 200 用例对比多模型

```bash
python -m nalana_eval.cli \
    --cases 200 \
    --models gpt-5,claude-sonnet-4-6,gemini-2.5-pro \
    --difficulty-dist short:0.4,medium:0.4,long:0.2 \
    --pass-at-k 3 \
    --judge-model gpt-4o \
    --workers 8
```

### 步骤 5：看历史趋势

```bash
# 最近 5 次同模型对比
python -m nalana_eval.cli history --model gpt-5 --last 5

# 多模型 head-to-head
python -m nalana_eval.cli history --compare gpt-5,claude-sonnet-4-6
```

---

## 文档导航

读哪份文档取决于你想做什么：

| 你想做 | 读这个 |
|---|---|
| **理解整个系统的设计哲学和架构** | [`docs/DESIGN.md`](docs/DESIGN.md) ← **必读** |
| **学会用 CLI** | [`docs/USAGE_GUIDE.md`](docs/USAGE_GUIDE.md) |
| **写新的 test case** | [`docs/TEST_CASE_AUTHORING.md`](docs/TEST_CASE_AUTHORING.md) |
| **了解技术架构细节** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| **从 v2.0 旧系统迁移** | [`docs/MIGRATION_FROM_V2.md`](docs/MIGRATION_FROM_V2.md) |
| **建立 LLM 评委的校准集** | [`calibration/README.md`](calibration/README.md) |
| **理解 CSV 数据库的字段** | [`docs/CSV_SCHEMA.md`](docs/CSV_SCHEMA.md) |

---

## 核心理念（30 秒版本）

### 旧系统问题

旧版评测以"复制人类设计师的 Blender 操作步骤"为核心。AI 创作场景下不成立——同一个"画苹果"指令，圆苹果、卡通苹果、写实苹果都可能是对的。

### 新系统理念

把 **"对答案"** 换成 **"对约束"**：

- **硬约束**（必须满足）：场景里有几个对象、bounding box 范围、材质颜色 ……
- **拓扑约束**（必须满足）：是否流形、quad ratio、最大面数
- **软约束**（评分）：顶点数、面数等连续指标加权
- **风格意图 + LLM 评委**（软信号）：判断"像不像"、"美不美"

不再追求"操作步骤一致"，只追求"输出符合用户期望"。

### 三层架构

```
L3 偏好对齐：LLM-as-Judge（现已实施）+ 未来 DPO
L2 约束验证：主 benchmark，可规模化到 1000+ 用例
L1 API 单元测试：v2.0 旧用例改造，仅防止确定性操作回归
```

---

## 仓库结构

```
Nalana-eval/
├── README.md                       ← 你正在看
├── docs/                           ← 所有文档
│   ├── DESIGN.md                   ← 设计哲学 + 架构（"宪法"）
│   ├── USAGE_GUIDE.md              ← CLI 用法详解
│   ├── TEST_CASE_AUTHORING.md      ← 用例编写规范
│   ├── ARCHITECTURE.md             ← 代码层架构
│   ├── MIGRATION_FROM_V2.md        ← 从旧 v2.0 迁移
│   └── CSV_SCHEMA.md               ← 数据库字段定义
│
├── nalana_eval/                    ← 主包
│   ├── schema.py                   ← v3.0 数据模型
│   ├── legacy_schema.py            ← v2.0（保留作 L1 单元测试）
│   ├── contracts.py                ← JSON 规范化 + safety allowlist
│   ├── dispatcher.py               ← JSON → bpy.ops 翻译器
│   ├── executor.py                 ← Blender 端执行（在 worker 内运行）
│   ├── scene_capture.py            ← 场景统计抓取
│   ├── screenshot.py               ← Workbench 渲染截图
│   ├── evaluator.py                ← L2 约束评估
│   ├── judge.py                    ← L3 LLM-as-Judge
│   ├── reporting.py                ← report.md / report.json 生成
│   ├── csv_db.py                   ← CSV 数据库读写
│   ├── runners/                    ← 多 LLM provider 适配器
│   │   ├── base.py
│   │   ├── openai_runner.py
│   │   ├── anthropic_runner.py
│   │   ├── gemini_runner.py
│   │   └── mock_runner.py
│   ├── workers/                    ← Blender worker 执行模式
│   │   ├── pool.py                 ← 默认 worker pool
│   │   ├── worker_loop.py          ← Blender 内部脚本
│   │   └── simple_runner.py        ← --simple-mode 入口
│   ├── history.py                  ← nalana-eval-history 实现
│   ├── review.py                   ← nalana-eval-review 实现
│   └── cli.py                      ← 主 CLI 入口
│
├── prompts/                        ← system prompt 配置
│   ├── eval_default.md             ← 默认中性 prompt
│   ├── nalana_prod.md              ← Nalana 生产 prompt
│   └── judge_prompt.md             ← 判官 prompt 模板
│
├── fixtures/                       ← 测试用例
│   ├── starter_v3/                 ← v3.0 starter cases (~30 条)
│   ├── legacy_v2/                  ← v2.0 保留作 L1 单元测试
│   └── synthetic/                  ← 程序化生成器
│       └── generate_cases.py
│
├── calibration/                    ← 判官校准集
│   ├── README.md                   ← 校准集说明书
│   ├── reference_images/           ← 用户放参考图（gitignored）
│   ├── calibrate.py                ← 校准命令
│   └── baseline_results/           ← 校准基线（gitignored）
│
├── db/                             ← 数据库（gitignored）
│   ├── runs.csv                    ← 每次 run 的汇总
│   ├── attempts.csv                ← 每个 attempt 细粒度
│   ├── judge_vs_human.csv          ← 判官 vs 人审对比积累
│   └── judge_cache.sqlite          ← 判官调用缓存
│
├── tests/                          ← 工程单元测试（pytest）
│   ├── test_schema.py
│   ├── test_contracts.py
│   ├── test_dispatcher.py
│   ├── test_evaluator.py
│   └── test_judge.py
│
├── artifacts/                      ← 单次 run 输出（gitignored）
│
├── requirements.txt
├── pyproject.toml
└── .gitignore
```

---

## CSV 数据库在哪里看？

你 workspace 的 `db/runs.csv` 和 `db/attempts.csv` 是普通 CSV 文件。四种查看方式：

1. **直接 Excel / Numbers 打开**——双击就行
2. **`nalana-eval-history` CLI**——出对比表 + ASCII 趋势图
3. **VS Code / Cursor + CSV 插件**（如 Rainbow CSV）
4. **DuckDB SQL 查询**：`duckdb -c "SELECT model_id, AVG(hard_pass_rate) FROM 'db/runs.csv' GROUP BY model_id"`

`db/` 在 `.gitignore` 里只是不进 git 历史，不影响本地浏览。

---

## 与旧版（v2.0）的关系

旧版基于 ground truth 步骤对比。新版基于约束验证。**v2.0 不会被删除**——它会变成 L1 层的"API 单元测试套件"，专门防止确定性操作（删除/撤销/默认 primitive 等）的回归。

迁移细节见 [`docs/MIGRATION_FROM_V2.md`](docs/MIGRATION_FROM_V2.md)。

---

## 谁维护这个系统

Nalana 工程团队。提 issue / PR 都欢迎。

---

**下一步建议读：[`docs/DESIGN.md`](docs/DESIGN.md)（理解为什么这样设计）→ [`docs/USAGE_GUIDE.md`](docs/USAGE_GUIDE.md)（学怎么用）→ [`docs/TEST_CASE_AUTHORING.md`](docs/TEST_CASE_AUTHORING.md)（学怎么写新用例）。**
