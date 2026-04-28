# Task #14 — Wizard CLI 交接说明

> 给接手 Task #14（`nalana-eval wizard` 交互式子命令）的工程师。这份文档自包含——配合 `SYSTEM_MAP.zh.md` 读完就够。

**English version**: [`HANDOFF_TASK_14.md`](HANDOFF_TASK_14.md)

---

## TL;DR

你要做的是一个交互式子命令 `nalana-eval wizard`，引导用户配置 benchmark run，然后打印对应的命令或者直接执行。类似 `npm init` 或 `create-react-app` 的提问流程。

这件事**和 #13 独立**——今天就能开干。只有一个小依赖点会在后续补 5 分钟即可，详见末尾"#13 依赖说明"。

**预计工作量**：0.5–1 天。

---

## 先读这些（15 分钟入门）

| 文档 | 为什么读 |
|---|---|
| `docs/SYSTEM_MAP.zh.md` | 一页式 4 层架构概览。Wizard 触碰的是横切的 CLI 层。 |
| `docs/USAGE_GUIDE.zh.md`（参数表） | 主 CLI 有 17 个 flag，wizard 要把它们暴露出来。不要重新发明，照搬。 |
| `nalana_eval/cli.py`（现有代码） | 子命令注册结构。Wizard 是 `history` / `review` / `calibrate` 之后的又一个子命令。 |

不需要读 DESIGN.md。这是 UX / 脚手架任务，不是架构改动。

---

## 你要做的东西

一个 CLI 子命令 `python -m nalana_eval.cli wizard`，做四件事：

1. **交互式问用户**关于 benchmark 的配置（问题列表见下）
2. **校验输入**——和主 CLI 用同一套逻辑（模型名在已知列表、分布百分比加起来 = 1.0 等）
3. **打印对应的 `python -m nalana_eval.cli ...` 命令**，让用户学到 flag 用法
4. **可选：立刻执行 benchmark**（最后一个 yes/no 问题）

**为什么要这个**：主 CLI 17 个 flag 太多。新人不知道哪些必填、哪些有合理默认、哪些组合合法。Wizard 是教学工具兼跑分入口。

---

## 要新建 / 修改的文件

| 文件 | 动作 | 说明 |
|---|---|---|
| `nalana_eval/wizard.py` | **新建** | 新模块。包含 `run_wizard()` 和 helper 提问函数。 |
| `nalana_eval/cli.py` | **修改** | 注册 `wizard` 子命令。照 `history` / `review` / `calibrate` 的模式来。 |
| `tests/test_wizard.py` | **新建** | 单元测试，用 `monkeypatch` mock 掉 `input()` / `sys.stdin`。覆盖 happy path + 非法输入。 |
| `docs/USAGE_GUIDE.md` + `.zh.md` | **修改** | 在 Quick Reference 之后加一段 "Wizard mode"。 |
| `docs/USAGE_GUIDE.md` 表格 | **修改** | 在 Auxiliary CLIs 表格里加 `wizard` 一行。 |

**不要碰**：`schema.py`、`evaluator.py`、`judge.py`、`runners/`、`workers/`、`dispatcher.py`、`executor.py`、`screenshot.py`、`scene_capture.py`、`reporting.py`、`csv_db.py`。Wizard 都用不到。

---

## 提问流程（按顺序）

每个问题都展示一个默认值，用户按 Enter 接受默认。

| # | 问题 | 默认 | 校验 |
|---|---|---|---|
| 1 | "测哪些模型？"（逗号分隔） | `gpt-5` | 必须在已知模型列表里（看 `runners/__init__.py` 的工厂） |
| 2 | "跑多少 case？" | `30`（smoke test） | 正整数，≤ suite 容量 |
| 3 | "用哪个 suite？" | `fixtures/starter_v3` | 路径必须存在 |
| 4 | "难度分布？"（如 `short:0.4,medium:0.4,long:0.2`） | `uniform` | 百分比之和 = 1.0 ± 0.01 |
| 5 | "Pass@k？" | `3` | 整数 1–10 |
| 6 | "判官模型？（或填 'skip' 禁用）" | `gpt-4o` | 在判官模型列表里，或 `skip` |
| 7 | "Worker 数？" | `cpu_count() * 0.75` | 整数 1–32 |
| 8 | "输出目录？" | `artifacts/` | 路径可写（不存在则创建） |
| 9 | "System prompt？（eval-default / nalana-prod）" | `eval-default` | 二选一 |
| 10 | "打印命令、执行、还是都做？" | `both` | `print` / `execute` / `both` |

第 10 题之后打印拼好的 CLI 命令。如果用户选了 `execute` 或 `both`，调主 benchmark 函数（**不要 shell out**——作为 Python 函数调用，错误能正确传播）。

---

## 实现提示

### 选交互库

三选一，挑**摩擦最小**的：

1. **stdlib 的 `input()`**——零依赖。如果你想保持 `requirements.txt` 干净选这个。需要自己写校验循环（`while True: ... if valid break`）。
2. **`questionary`**——现代库，支持默认值 / 校验器 / 方向键选择。加到 `requirements.txt`。**推荐**。
3. **`inquirer`**——questionary 的老前辈，同样思路。

不确定就用 `questionary`。

### 镜像现有 CLI 模式

`cli.py` 用 `argparse` 加 subparsers。`history` / `review` / `calibrate` 的模式大致是：

```python
# 在 cli.py 里
sub_wizard = subparsers.add_parser("wizard", help="Interactive setup wizard")
sub_wizard.set_defaults(func=run_wizard_cli)

def run_wizard_cli(args):
    from nalana_eval.wizard import run_wizard
    run_wizard()
```

### 校验代码不要复制

主 CLI 已经有的校验逻辑（模型名查找、分布解析等），**直接 import 复用**。如果某个校验目前没拆成独立函数，**就把它从主 CLI 抽出来**变成共享 util——这是一次合理的小重构。

### 别过度设计

Wizard 是薄薄一层 UX。**不要状态机、不要插件系统、不要配置文件持久化**。一串问题 → CLI 字符串 → 可选执行就够。`wizard.py` ≤ 200 行是合理范围。

---

## 验收标准

完成意味着以下都做到：

- [ ] `python -m nalana_eval.cli wizard` 启动提问流
- [ ] 10 个问题按顺序问，都有合理默认
- [ ] 每题敲 Enter 接受默认
- [ ] 非法输入重新提问 + 清晰错误（不崩）
- [ ] 最终输出可复制粘贴的 `python -m nalana_eval.cli ...`
- [ ] `execute` / `both` 选项能真跑 benchmark
- [ ] `tests/test_wizard.py` 覆盖：完整 happy path、非法 model name、分布之和不对、全默认走完
- [ ] `pytest` 通过
- [ ] `docs/USAGE_GUIDE.md`（和 `.zh.md`）新增 "Wizard mode" 段，附一个示例 session

---

## 本地开发

```bash
# 配环境
cd ~/Nalana-eval
pip install -r requirements.txt    # （+ questionary 如果选了它）

# 不烧 API 钱，用 mock runner
export OPENAI_API_KEY=sk-fake
python -m nalana_eval.cli wizard
# 当 wizard 问 model 时，输入：mock-model

# 跑测试
pytest tests/test_wizard.py -v

# 真实跑通 wizard → execute 路径，省钱模式
python -m nalana_eval.cli wizard
# 选：gpt-5, 5 cases, simple-mode, judge=skip
```

---

## #13 依赖说明（唯一的）

另一个 task（#13）正在给 `TestCaseCard` schema 加 `tags: List[Tag]` 字段，值是 `canonical` / `adversarial` / `ambiguous` / `multi_object` / `stylized` 等。让用户能按 tag 过滤。

**当前阶段：不要在 wizard 里问 tag 过滤问题**。schema 还没这个字段，问了也没用。

**等 #13 的 schema 改动 ship 之后**（你会看到一个新 commit 改 `nalana_eval/schema.py` 加 `Tag` enum 和 `tags` 字段），回来在第 5 题（Pass@k）和第 6 题（Judge model）之间加一题：

> "按 tag 过滤 case？（canonical / adversarial / stylized / multi_object / skip）"

从 `Tag.__members__` 读可用值，这样 enum 扩展时问题自动同步。这是 5–10 分钟的小补丁——单开一个 PR。

#13 准备好的标志：
- `Tag` enum 可以从 `nalana_eval.schema` import
- 现有 fixtures 有非空的 `tags` 数组
- 主 CLI 接受 `--tags canonical,stylized`

---

## Git 工作流

这个 repo 现在用一条持久分支（`ian_workspace`）做主线工作，但你应该开自己的分支：

```bash
git checkout main
git pull
git checkout -b <你的名字>/task-14-wizard
# ... 边写边 commit ...
git push -u origin <你的名字>/task-14-wizard
```

验收标准全过之后，对 `main` 开 PR。tag `@ian`（或当前 task-14 reviewer）找人 review。

---

## 常见坑

- **M 系列 Mac 上 `cpu_count()` 把性能核 + 效率核都算进去**。默认 `cpu_count() * 0.75` 会过分配。主 CLI 已经处理过，复用它，别重新发明。
- **`input()` 在某些 IDE 控制台不工作**。从真实终端测，不要用 VS Code 的"Run Python File"按钮测。
- **不要在 wizard 里调 `sys.exit()`**。返回结构化结果，让 CLI 调度器决定是否退出。

---

## 哪里问问题

- 架构 / 设计问题 → 先读 `docs/DESIGN.md`，然后 ping `@ian`
- Pydantic / schema 问题 → 先读 `docs/SYSTEM_MAP.zh.md`，然后 ping `@ian`
- "现有 CLI 是怎么处理 X 的？" → 先 grep `cli.py`，然后 ping `@ian`
- 卡住超过 30 分钟 → ping `@ian`，别空转

PR 规范：小 commit、清楚的 message、PR description 里 link 这份文档让 reviewer 知道上下文。

欢迎加入。🚀
