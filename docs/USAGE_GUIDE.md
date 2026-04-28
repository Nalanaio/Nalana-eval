# Nalana 评测系统使用指南（CLI Usage Guide）

> 本文档教你**怎么用**这个系统。如果你想理解**为什么这样设计**，先读 `DESIGN.md`。

---

## 目录

- [前置：装环境](#前置装环境)
- [常用命令速查](#常用命令速查)
- [主命令：`nalana-eval`](#主命令-nalana-eval)
- [辅助命令：`nalana-eval-history`](#辅助命令-nalana-eval-history)
- [辅助命令：`nalana-eval-review`](#辅助命令-nalana-eval-review)
- [辅助命令：`nalana-eval-calibrate`](#辅助命令-nalana-eval-calibrate)
- [Run folder 长什么样](#run-folder-长什么样)
- [怎么读 report.md](#怎么读-reportmd)
- [常见使用场景](#常见使用场景)
- [常见问题排查](#常见问题排查)

---

## 前置：装环境

### 1. Python 依赖

```bash
cd /Users/ianian/Nalana-eval
python -m venv .venv         # 推荐用虚拟环境
source .venv/bin/activate    # Linux/macOS
pip install -r requirements.txt
```

### 2. Blender 4.0+

评测系统需要在外部调用 Blender 跑 case：

```bash
# macOS
brew install --cask blender

# Linux (Ubuntu/Debian)
sudo snap install blender --classic

# 或从官网下载：https://www.blender.org/download/
```

**验证**：

```bash
blender --version    # 应该输出 Blender 4.x.x
```

如果 `blender` 不在 PATH 中，设置环境变量：

```bash
export BLENDER_BIN=/Applications/Blender.app/Contents/MacOS/Blender   # macOS 示例
```

### 3. API key 配置

**推荐**：写到 `.env` 文件（仓库根目录），系统会自动加载。

```bash
cat > .env <<EOF
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
EOF
```

**安全提醒**：`.env` 已在 `.gitignore` 里，不会进 git。**永远不要**把 API key 直接放在命令行里——会留在 shell history。

只测部分模型时，只配那部分的 key 即可（缺失的会被跳过并在 report 里标记 `model_unavailable`）。

---

## 常用命令速查

```bash
# Smoke test（10 个 case，最快验证环境）
python -m nalana_eval.cli --cases 10 --models gpt-5 --simple-mode

# 主 benchmark（200 用例，多模型对比）
python -m nalana_eval.cli \
    --cases 200 --models gpt-5,claude-sonnet-4-6,gemini-2.5-pro \
    --pass-at-k 3 --workers 8

# 跑 legacy L1 单元测试套件（防回归）
python -m nalana_eval.cli --legacy-suite fixtures/legacy_v2/sample_cases_v2.json --models gpt-5

# 查看历史趋势
python -m nalana_eval.cli history --model gpt-5 --last 10

# 多模型对比表
python -m nalana_eval.cli history --compare gpt-5,claude-sonnet-4-6

# 收集人审反馈
python -m nalana_eval.cli review --collect artifacts/run_<id>/report.md

# 跑判官校准集
python -m nalana_eval.cli calibrate --judge-model gpt-4o
```

> **注**：所有子命令都通过 `python -m nalana_eval.cli <subcommand>` 调用。如果安装了 setuptools entry points，可以直接 `nalana-eval ...`、`nalana-eval-history ...` 等。

---

## 主命令：`nalana-eval`

### 完整参数表

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--cases N` | int | 全部 | 跑多少个 case（按 distribution 采样） |
| `--models M1,M2,...` | str | gpt-5 | 要测的 LLM，逗号分隔（串行执行） |
| `--suite path` | str | fixtures/starter_v3 | 测试用例目录或文件 |
| `--legacy-suite path` | str | none | 跑 L1 legacy 单元测试套件（v2.0 格式） |
| `--difficulty-dist` | str | uniform | 难度分布，例如 `short:0.3,medium:0.5,long:0.2` |
| `--pass-at-k k` | int | 3 | 每个 case 跑 k 次 attempt |
| `--workers N` | int | cpu_count*0.75 | Blender worker 数 |
| `--simple-mode` | flag | off | 退化为单次 subprocess 模式（慢但稳） |
| `--judge-model M` | str | gpt-4o | LLM 评委模型 |
| `--judge-budget USD` | float | 10.0 | 判官调用预算上限（美元） |
| `--no-judge` | flag | off | 完全禁用 LLM-as-Judge |
| `--system-prompt name` | str | eval-default | system prompt：`eval-default` 或 `nalana-prod` |
| `--temperature T` | float | 0.7 | LLM 采样温度 |
| `--seed N` | int | 42 | 随机种子（复现实验用） |
| `--output-dir path` | str | artifacts/ | run folder 输出位置 |
| `--api-keys-file path` | str | .env | API key 文件 |
| `--verbose` | flag | off | 详细日志 |

### 参数详解

#### `--cases` 与分布参数

```bash
# 用例数 = 200，按 difficulty 分布采样
--cases 200 --difficulty-dist short:0.4,medium:0.4,long:0.2
# 实际跑：80 short + 80 medium + 40 long
```

如果 suite 里某个分布 bucket 不够，会从其他 bucket 借（并在 report 里 warning）。

#### `--models` 多模型行为

逗号分隔的模型名，**串行**跑（不并发），原因：
1. 同家 API rate limit 不同模型无法共享
2. 不同家 API 可以并行，但日志混在一起难调试
3. 串行时间可控（200 用例 × 3 模型 ≈ 30 分钟）

每个模型产出独立的 run folder。CSV `db/runs.csv` 会有 N 行（每模型一行），但共享同一 `run_group_id`。

#### `--pass-at-k`

`k=1`：每 case 跑 1 次。最快，但抓不到 LLM 随机性。
`k=3`（**默认**）：每 case 跑 3 次。SWE-bench 行业标准。
`k=5`：更稳的 pass rate 估计，5 倍成本。

每次 attempt 用不同的 prompt variant（如果 case 有多个 `prompt_variants`），并轮转 temperature seed。

#### `--workers` 与执行模式

| 模式 | 1000 用例耗时 | 适用场景 |
|---|---|---|
| Worker pool（默认）| 5-10 分钟 | 平时正式 benchmark |
| `--simple-mode` | 30-50 分钟 | CI、debug、第一次跑 |

worker pool 会启动 N 个常驻 `blender --background` 进程，case 之间用 `read_factory_settings(use_empty=True)` 重置场景。每 100 用例自动重启 worker（防内存泄漏）。

#### `--judge-model` 与 `--judge-budget`

```bash
# 单判官（默认）
--judge-model gpt-4o

# 双判官求平均（更降偏，2 倍成本）
--judge-model gpt-4o,claude-sonnet-4-6
```

预算超额时跳过剩余判官调用，report 里标 `judge skipped: budget exceeded`。

#### `--system-prompt`

| 值 | 用什么 prompt | 测什么 |
|---|---|---|
| `eval-default`（默认）| `prompts/eval_default.md` 中性 prompt | **裸 LLM 在公平测试下的能力** |
| `nalana-prod` | `prompts/nalana_prod.md`（复制自生产） | **加了 Nalana 业务 prompt 后的端到端表现** |

模型对比时**必须用同一个 system prompt**，否则不公平。

---

## 辅助命令：`nalana-eval-history`

读 `db/runs.csv` + `db/attempts.csv`，输出趋势/对比。

### 用法

```bash
# 单模型最近 N 次趋势
python -m nalana_eval.cli history --model gpt-5 --last 10
# 输出 ASCII 折线 + 关键指标表

# 多模型 head-to-head
python -m nalana_eval.cli history --compare gpt-5,claude-sonnet-4-6 --metric hard_pass_rate

# 单 case 历史
python -m nalana_eval.cli history --case CV-OBJ-042 --model gpt-5

# 输出 CSV / JSON
python -m nalana_eval.cli history --model gpt-5 --last 10 --format json > trend.json

# 出 PNG 趋势图（需 matplotlib）
python -m nalana_eval.cli history --model gpt-5 --last 10 --plot trend.png
```

---

## 辅助命令：`nalana-eval-review`

收集 `report.md` 里的 `HUMAN_REVIEW_BLOCK`，回填到 `db/attempts.csv` 的 `judge_human_override` 等列。

### 工作流

1. 跑完 benchmark，打开 `artifacts/run_<id>/report.md`
2. 在浏览器/编辑器里看每个 case 的截图 + 判官打分
3. **觉得判官打错了？** 在那个 case 的 `<!-- HUMAN_REVIEW_BLOCK -->` 里改：

   ```markdown
   <!-- HUMAN_REVIEW_BLOCK:CV-OBJ-042:attempt_0
   override: disagree           ← 改成 agree / disagree / partial
   corrected_semantic: 5        ← 你认为正确的分（5 分制）
   corrected_aesthetic: 4
   corrected_professional: 3
   reviewer: ian                ← 你的名字
   note: 判官没识别出这是卡通风格    ← 任意说明
   END_HUMAN_REVIEW_BLOCK -->
   ```

4. 跑回收命令：

   ```bash
   python -m nalana_eval.cli review --collect artifacts/run_<id>/report.md
   ```

   系统会解析所有 review block，写回 `db/attempts.csv` 对应行的 `judge_human_override` 等列，同时追加到 `db/judge_vs_human.csv` 累积学习数据。

5. 多人 review 同一个 run：每人 review 完都跑一次 `--collect`。后写的覆盖前写的（同一 case + reviewer 唯一），会保留所有 reviewer 的记录。

### 批量 review

```bash
# 批量收集多个 run
python -m nalana_eval.cli review --collect-glob 'artifacts/run_*/report.md'

# 只看待 review 的（override: pending）
python -m nalana_eval.cli review --pending --run <run_id>
```

---

## 辅助命令：`nalana-eval-calibrate`

跑判官校准集，检测 LLM 评委的系统性偏差。详见 `calibration/README.md`。

### 快速校准

```bash
# 跑全部校准集（cartoon + realistic + low-poly 各 20-30 张）
python -m nalana_eval.cli calibrate --judge-model gpt-4o

# 只跑某个风格
python -m nalana_eval.cli calibrate --judge-model gpt-4o --style cartoon
```

输出 `calibration/baseline_results/<judge_model>_<timestamp>.json` 含：
- 每个风格的均分 + stddev
- 跨风格的偏差分析（卡通组 vs 写实组在各自标准下的均分差距）
- 建议（如果偏差 > 0.3 应换判官或调 prompt）

---

## Run folder 长什么样

每次 `nalana-eval` 运行产出一个独立文件夹：

```
artifacts/run_20260425_143022_<run_id_8>/
├── report.md                        ← 人类主报告（你最常看的）
├── report.json                      ← 完整结构化数据
├── failures.jsonl                   ← 失败 case 详细日志（调试用）
├── config.json                      ← 这次 run 的所有 CLI 参数
├── prompts_used.json                ← 这次 run 用了什么 system prompt
├── baseline_delta.json              ← 与上次同模型 run 的对比
│
├── screenshots/
│   ├── CV-OBJ-042_attempt_0.png         ← 原图 800×600
│   ├── CV-OBJ-042_attempt_0_thumb.png   ← 缩略图 512×384
│   ├── CV-OBJ-042_attempt_1.png
│   ├── CV-OBJ-042_attempt_1_thumb.png
│   └── ...
│
└── scene_stats/
    ├── CV-OBJ-042_attempt_0.json    ← bmesh 统计、bbox、对象列表、materials
    └── ...
```

**为什么每个 attempt 都有原图 + 缩略图？**

- 原图（800×600）：高清，给人审看细节
- 缩略图（512×384）：嵌入 markdown，加载快

`report.md` 用相对路径引用缩略图，点击跳转到原图：

```markdown
[![attempt 0](screenshots/CV-OBJ-042_attempt_0_thumb.png)](screenshots/CV-OBJ-042_attempt_0.png)
```

整个 run folder **可以打包发给任何人**，图片不会丢——所有路径都是相对的。

---

## 怎么读 report.md

`report.md` 的标准结构：

### 1. Executive Summary（开头）

模型对比的一张表：

```markdown
| Model | Hard Pass | Topology Pass | Avg Soft | Pass@3 | Judge Avg | Cost |
|---|---|---|---|---|---|---|
| gpt-5 | 78% | 85% | 0.72 | 91% | 3.8/5 | $4.21 |
| claude-sonnet-4-6 | 74% | 83% | 0.69 | 88% | 3.9/5 | $5.10 |
```

### 2. Distribution（输入结构）

这次 run 跑了什么：

```markdown
**Categories**: Object Creation: 80, Transformations: 50, Materials: 40, Compositional: 30
**Difficulty**: Short: 80, Medium: 80, Long: 40
```

### 3. Breakdown（按维度拆解）

每个 category / difficulty / task_family 的通过率，找模型的薄弱面。

### 4. Top Failure Reasons

按 `failure_class` 汇总，看模型最常在哪挂：

```markdown
1. CONSTRAINT_FAILED (23 cases)
   - 18 × bounding_box too small
   - 5  × material color mismatch
2. TOPOLOGY_FAILED (12 cases)
   - 12 × non-manifold edges
3. PARSE_ERROR (3 cases)
   - 3  × invalid JSON
```

### 5. Sample Cases

挑选**有代表性**的失败和边界用例展示：每个 case 内嵌缩略图、约束结果、判官分、`HUMAN_REVIEW_BLOCK`。

### 6. Baseline Delta

与上次同模型 run 对比的 delta（正数好、负数坏）：

```markdown
| Metric | This run | Last run | Delta |
|---|---|---|---|
| Hard Pass Rate | 78% | 76% | +2.0% ↑ |
| Pass@3 | 91% | 92% | -1.0% ↓ |
```

### 7. Judge Reliability

判官健康指标：诱饵被打高分了吗？方差大吗？

```markdown
- Honeypots correctly low-scored: 9/10 (90%) ✓
- Cases with judge_stddev > 1.0: 3 (1.5%) ✓
- Calibration drift since last run: +0.05 (within ±0.3 threshold) ✓
```

---

## 常见使用场景

### 场景 A：每天 smoke test（5 分钟）

每天上班花 5 分钟确认主模型没退化：

```bash
python -m nalana_eval.cli \
    --cases 30 --models gpt-5 --pass-at-k 1 --workers 4
```

看 `report.md` 的 Executive Summary 即可。

### 场景 B：发版前正式 benchmark（30-60 分钟）

模型即将上生产前完整跑一次：

```bash
python -m nalana_eval.cli \
    --cases 300 --models gpt-5 --pass-at-k 5 \
    --workers 8 --judge-model gpt-4o,claude-sonnet-4-6
```

红线：Pass-to-Pass = 100%，Hard Pass Rate 不能比上一版掉超过 5%。

### 场景 C：模型选型实验（2-3 小时）

要决定用哪个 LLM 做 Nalana 后端：

```bash
# 跑 200 用例 × 3 模型 × pass@3 = 1800 attempt
python -m nalana_eval.cli \
    --cases 200 \
    --models gpt-5,claude-sonnet-4-6,gemini-2.5-pro,gpt-4o \
    --pass-at-k 3 --workers 8
```

然后用 `nalana-eval-history --compare gpt-5,claude-sonnet-4-6` 看头对头对比。

### 场景 D：定位回归（troubleshooting）

某次 run 突然 Pass Rate 掉了 10%——

```bash
# 1. 看 baseline_delta.json 确认确实是回归
cat artifacts/run_<id>/baseline_delta.json

# 2. 看 failures.jsonl 找掉的 case
jq '.failure_class' artifacts/run_<id>/failures.jsonl | sort | uniq -c

# 3. 重跑那批失败的 case 仔细看
python -m nalana_eval.cli \
    --cases-from artifacts/run_<id>/failures.jsonl \
    --models gpt-5 --pass-at-k 1 --simple-mode --verbose
```

### 场景 E：调试某个 case 的判官打分

```bash
# 隔离跑单个 case，judge variance 拉到 5
python -m nalana_eval.cli \
    --case-ids CV-OBJ-042 \
    --models gpt-5 \
    --judge-runs 5 \
    --simple-mode --verbose
```

---

## 常见问题排查

### 错误：`blender: command not found`

设置 `BLENDER_BIN` 环境变量：

```bash
# macOS
export BLENDER_BIN=/Applications/Blender.app/Contents/MacOS/Blender

# Linux
export BLENDER_BIN=/snap/bin/blender
```

或安装 blender 到 PATH。

### 错误：`OPENAI_API_KEY not set`

检查 `.env` 是否在 cwd（仓库根目录）。或显式指定：

```bash
python -m nalana_eval.cli ... --api-keys-file /path/to/.env
```

### Blender worker 卡住、case 超时

通常是 worker 内存泄漏或某个 case 触发了 Blender bug。解决：

1. 减少 worker 数：`--workers 4`
2. 切到 simple mode：`--simple-mode`
3. 看 `failures.jsonl` 找触发 case，单独跑

### 判官给了不公平的分

走 `nalana-eval-review` 流程：在 report.md 里的 `HUMAN_REVIEW_BLOCK` 改 override，跑 `--collect`。

如果**全局**判官有偏差（不是个案），跑校准集：

```bash
python -m nalana_eval.cli calibrate --judge-model gpt-4o
```

如果 calibration drift > 0.3，考虑换判官模型或调 prompt（`prompts/judge_prompt.md`）。

### 跑了很多次，CSV 越来越大

```bash
# 看大小
ls -lh db/

# 归档 90 天前的数据
python -m nalana_eval.cli db archive --before 2026-01-01

# 或直接复制走然后清空
cp db/runs.csv db/runs_archive_2026Q1.csv
echo "" > db/runs.csv  # 危险！备份后再做
```

或迁移到 SQLite（详见 `docs/CSV_SCHEMA.md` 末尾）。

---

## 下一步

- 想自己写新 case → [`TEST_CASE_AUTHORING.md`](TEST_CASE_AUTHORING.md)
- 想理解代码层架构 → [`ARCHITECTURE.md`](ARCHITECTURE.md)
- 想改判官 prompt → [`../prompts/judge_prompt.md`](../prompts/judge_prompt.md) + 跑校准集验证
- 遇到 bug / 想加新功能 → 提 issue 或 PR
