# Nalana 评测系统 V3.0：实现简报（给 Claude Code 的接力棒）

> **本文档专门给在 IDE 里接手实现的 Claude Code（或人类工程师）看。**
> 它假设你已经读过 `DESIGN.md` 和 `ARCHITECTURE.md`，理解了系统的目标和架构。
> 本文档告诉你**逐文件该写什么、按什么顺序写、写完怎么验证**。

---

## 0. 你接手的状态

### 已完成（在 Cowork 阶段产出）

```
docs/
├── DESIGN.md                  ← 设计哲学 + 三层架构 + 判官机制
├── ARCHITECTURE.md            ← 模块依赖图 + 每个模块职责 + 数据流
├── USAGE_GUIDE.md             ← CLI 用法详解
├── TEST_CASE_AUTHORING.md     ← 用例编写规范
├── CSV_SCHEMA.md              ← 数据库字段定义
├── MIGRATION_FROM_V2.md       ← 从 v2.0 迁移
└── IMPLEMENTATION_BRIEF.md    ← 你正在读

prompts/
├── eval_default.md            ← 默认中性 system prompt
├── nalana_prod.md             ← Nalana 生产 prompt
└── judge_prompt.md            ← 判官 prompt 模板

calibration/
└── README.md                  ← 校准集说明书

README.md                      ← 仓库主入口
.gitignore
db/.gitkeep
calibration/reference_images/.gitkeep
```

### 需要你做（按建议顺序）

**Phase A：基础数据层（先写，所有人依赖）**
1. `nalana_eval/__init__.py`
2. `nalana_eval/schema.py`
3. `nalana_eval/legacy_schema.py`
4. `nalana_eval/contracts.py`
5. `tests/test_schema.py` + `tests/test_contracts.py`

**Phase B：Blender 端（在 Blender 进程内运行的代码）**
6. `nalana_eval/dispatcher.py`
7. `nalana_eval/scene_capture.py`
8. `nalana_eval/screenshot.py`
9. `nalana_eval/workers/worker_loop.py`
10. `nalana_eval/workers/single_run.py`

**Phase C：评测端（在主 Python 进程运行的代码）**
11. `nalana_eval/evaluator.py`
12. `nalana_eval/judge.py`
13. `nalana_eval/runners/base.py` + `runners/openai_runner.py` + `runners/anthropic_runner.py` + `runners/gemini_runner.py` + `runners/mock_runner.py`
14. `nalana_eval/workers/pool.py`
15. `nalana_eval/workers/simple_runner.py`
16. `nalana_eval/csv_db.py`
17. `nalana_eval/reporting.py`
18. `nalana_eval/harness.py`

**Phase D：CLI + 周边工具**
19. `nalana_eval/cli.py`
20. `nalana_eval/history.py`
21. `nalana_eval/review.py`
22. `calibration/calibrate.py`
23. `fixtures/synthetic/generate_cases.py`
24. `fixtures/starter_v3/*.json`（手写 ~30 条 case）

**Phase E：集成测试**
25. `tests/test_evaluator.py` / `test_judge.py` / `test_csv_db.py`
26. `tests/test_e2e_smoke.py`（mock LLM + mock Blender 跑通 5 case）

**Phase F：打包**
27. `requirements.txt` / `pyproject.toml`
28. `Makefile` 或 `scripts/`（常用命令）

---

## 1. 实现风格指南

### 1.1 类型注解必须有

所有函数签名必须有完整的类型注解。pydantic 模型 + `from __future__ import annotations`。

### 1.2 错误优先于成功

每个外部 IO（API 调用、subprocess、文件读写）都用 try/except 包，**绝对不允许 unhandled exception 中断整个 run**。失败时返回 `failure_class` + `error_message`，让 run 继续。

### 1.3 没有"魔法字符串"

所有 enum 值、字段名、路径常量集中在 `schema.py` 或 `constants.py`。**不要**在多个文件里写 `"Object Creation"` 这样的字符串。

### 1.4 不写"通用工具"模块

如果某个函数只被一个地方用，就放在那个文件里。**不要**预先建 `utils.py` 或 `helpers.py`。

### 1.5 分层 import

```
schema.py             ← 不 import 任何项目内模块
contracts.py          ← 只 import schema
dispatcher.py         ← import schema + bpy（Blender 内）
evaluator.py          ← import schema
judge.py              ← import schema
runners/*.py          ← import schema + contracts
workers/*.py          ← import schema + dispatcher（worker_loop 内）+ subprocess（pool 内）
reporting.py          ← import schema + 所有上面
csv_db.py             ← import schema
harness.py            ← import 上面所有
cli.py                ← import harness + 周边
```

import 出现循环 = 设计有问题，停下来重构而不是绕过。

### 1.6 所有路径用 pathlib

```python
from pathlib import Path
output = Path(args.output_dir) / f"run_{timestamp}_{run_id}"
```

避免字符串拼路径。

### 1.7 日志而不是 print

```python
import logging
logger = logging.getLogger(__name__)
logger.info("Loaded suite with %d cases", len(suite.cases))
```

CLI `--verbose` 切换 logging level。

---

## 2. 逐 Phase 的实现规范

### Phase A：基础数据层

#### A.1 `nalana_eval/schema.py`

参考 `Nalana-datasc/testing/benchmark/schema.py` —— **它已经有 v3.0 schema 的雏形**，直接 fork 过来再迭代。

需要新增的字段（相对 Nalana-datasc 现状）：

- `StyleIntent` 模型（见 ARCHITECTURE.md 2.2 节字段定义）
- `JudgePolicy` enum：`SKIP / SCORE / AUDIT_ONLY`
- `JudgeResult` 模型（见 ARCHITECTURE.md 2.2 节）
- `TestCaseCard` 加 `style_intent` + `judge_policy` 字段
- `AttemptArtifact` 加 `judge_result` 字段
- `BenchmarkRunConfig` 模型：保存 CLI 参数快照

完成后跑：
```bash
pytest tests/test_schema.py -v
```

#### A.2 `nalana_eval/legacy_schema.py`

直接复制 `Nalana-eval/schema.py`（当前的 v2.0），**不修改字段**。改 import 路径以适配新包名。

测试要确认 v2.0 cases 仍能加载：
```bash
pytest tests/test_schema.py::test_legacy_v2_loads -v
```

#### A.3 `nalana_eval/contracts.py`

直接 fork `Nalana-datasc/testing/benchmark/contracts.py`，行为不变。新增的事项：

- 提取 `ALLOWED_PRIMITIVES` 等到模块级常量，方便文档引用
- 加 `compute_normalization_signature(steps) -> str`，返回 step 列表的 sha256（用于判官缓存 key）

测试要覆盖：
- 三种 contract 都能正确归一化
- 危险操作（如 `bpy.ops.wm.quit_blender`）被 reject
- 边界值（`radius=0`、`segments=257`）报错

---

### Phase B：Blender 端

⚠️ **关键约束**：这一层的所有代码会在 `blender --background --python` 下跑，**只能用 Blender 自带的 Python**——不能 import 第三方库（包括 pydantic、Pillow 等）。

#### B.1 `nalana_eval/dispatcher.py`

参考现有 `Nalana-eval/executor.py` 的 `DualContractExecutor` 类：把它拆成纯 dispatcher（无 pydantic 依赖）+ 在 worker_loop 里包装成完整流程。

关键 API：

```python
def reset_scene(initial_scene_dict: dict) -> None: ...
def execute_normalized_steps(steps: List[dict]) -> None: ...
# ↑ 注意：传 dict，不传 NormalizedStep 对象，因为 worker 内没有 pydantic
```

allowlist 用 module-level dict，参考现有 `legacy_registry`。

#### B.2 `nalana_eval/scene_capture.py`

参考现有 `executor.py` 的 `capture_scene_snapshot()` 方法，原样移植。返回 dict（不返回 pydantic 对象，因为 worker 内没有 pydantic）。

主进程收到 dict 后再 `SceneSnapshot.model_validate(dict)`。

#### B.3 `nalana_eval/screenshot.py`

按 `ARCHITECTURE.md` 第 2.9 节的方案实现。**关键**：
- 用 `BLENDER_WORKBENCH` 引擎（不是 EEVEE/Cycles）
- 程序化等距相机摆放（基于所有 mesh 对象的 bbox）
- 800×600 PNG
- 缩略图用 PIL（在主进程做，**不在 worker 内做**——worker 没有 PIL）

worker 只负责出原图，主进程拿到原图后调 `make_thumbnail()`。

#### B.4 `nalana_eval/workers/worker_loop.py`

完整流程见 `ARCHITECTURE.md` 第 2.6.2 节。关键：

```python
import sys, json
import bpy

# Blender Python 路径设置（让 dispatcher.py 等可被 import）
import os
sys.path.insert(0, os.environ.get("NALANA_EVAL_RUNTIME_PATH", "."))

from dispatcher import reset_scene, execute_normalized_steps
from scene_capture import capture
from screenshot import render_scene_to_png

while True:
    line = sys.stdin.readline()
    if not line:
        break
    msg = json.loads(line)
    cmd = msg.get("command")

    if cmd == "exit":
        break

    if cmd == "ping":
        sys.stdout.write(json.dumps({"pong": True}) + "\n")
        sys.stdout.flush()
        continue

    if cmd == "run_case":
        try:
            result = run_one_case(msg)
        except Exception as e:
            result = {"ok": False, "error": str(e), "failure_class": "EXECUTION_ERROR"}
        sys.stdout.write(json.dumps(result) + "\n")
        sys.stdout.flush()
```

**调试技巧**：worker 的 stderr 别走 pipe（容易堵）；让 stderr 直接打印到 console，主进程不读。

#### B.5 `nalana_eval/workers/single_run.py`

`--simple-mode` 用：单次 Blender 调用，从 input.json 读 case，写 output.json。

```python
# blender --background --python single_run.py -- input.json output.json
import sys, json, bpy

argv = sys.argv[sys.argv.index("--") + 1:]
input_path, output_path = argv

with open(input_path) as f:
    msg = json.load(f)

# 同 worker_loop 里的 run_one_case
result = run_one_case(msg)

with open(output_path, "w") as f:
    json.dump(result, f)
```

---

### Phase C：评测端

#### C.1 `nalana_eval/evaluator.py`

按 `ARCHITECTURE.md` 第 2.10 节实现。每种 hard constraint 一个 `_check_*` 函数：

```python
def _check_mesh_object_count(constraint, snapshot) -> Optional[str]: ...
def _check_required_object_types(...) -> Optional[str]: ...
def _check_bounding_boxes(...) -> Optional[str]: ...
def _check_materials(...) -> Optional[str]: ...
# 返回 None 表示通过，返回 str 表示违规描述
```

**容差处理**：所有数值约束都按 case 提供的 `tolerance` 走，默认 0。Color 比较用 RGB 欧氏距离。

#### C.2 `nalana_eval/judge.py`

按 `ARCHITECTURE.md` 第 2.11 节 + `prompts/judge_prompt.md` 模板实现。

判官调用结构：

```python
def _build_messages(case, screenshot_path, prompt_used) -> list:
    """构造 OpenAI/Anthropic/Gemini 通用的 messages 结构。"""
    with open(screenshot_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    judge_template = load_prompt_template("prompts/judge_prompt.md")
    rendered = judge_template.format(
        prompt_used=prompt_used,
        style_intent=json.dumps(case.style_intent.model_dump(), ensure_ascii=False),
    )

    return [
        {"role": "system", "content": "You are a 3D modeling reviewer..."},
        {"role": "user", "content": [
            {"type": "text", "text": rendered},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]},
    ]
```

**Cache 实现**：`db/judge_cache.sqlite` 一张表 `judge_cache(key TEXT PRIMARY KEY, result_json TEXT, created_at TIMESTAMP)`。

**Honeypot**：harness 决定何时插入诱饵（每 10 个 case 一次），judge 不感知。诱饵的 case_id 加前缀 `HONEYPOT_`，judge 完成评分后 harness 单独检查"诱饵分数是否合理低（<= 2/5）"。

#### C.3 `nalana_eval/runners/`

每个 runner 子类实现 `_generate(prompt, **kwargs)`。

**OpenAI**（推荐 `response_format={"type": "json_object"}` 强制 JSON 输出）：

```python
class OpenAIRunner(BaseModelRunner):
    PRICING = {
        "gpt-5": {"input": 0.0125, "output": 0.05},        # per 1k tokens, USD
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    }

    def _generate(self, prompt: str, temperature: float, seed: int) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.model_id,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            seed=seed,
            response_format={"type": "json_object"},
        )
        self.last_usage = resp.usage
        return resp.choices[0].message.content
```

**Anthropic**（Claude 不支持 `response_format`，用 prompt 工程强制 JSON）：

```python
class AnthropicRunner(BaseModelRunner):
    def _generate(self, prompt: str, temperature: float, seed: int) -> str:
        # Anthropic 没有 seed 参数，忽略
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.model_id,
            max_tokens=2048,
            system=self.system_prompt + "\n\nIMPORTANT: Output ONLY valid JSON, no prose.",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return resp.content[0].text
```

**Gemini**：用 `google.genai`。**注意**：Gemini 2.5 Pro 用的是 `google.genai` SDK，参考 Nalana-datasc/live_bridge.py 第 24 行的 import 方式。

**Mock**（用于测试）：

```python
class MockRunner(BaseModelRunner):
    """从 fixture JSON 文件读预录的输出，按 case_id + attempt_index 索引。"""
    def __init__(self, payload_file: str, **kwargs):
        super().__init__(model_id="mock", **kwargs)
        self.payloads = json.load(open(payload_file))

    def _generate(self, prompt, temperature, seed):
        # 用 prompt hash 作 fallback key
        key = self.current_case_key
        return json.dumps(self.payloads[key])
```

#### C.4 `nalana_eval/workers/pool.py`

按 `ARCHITECTURE.md` 第 2.6.1 节。关键实现注意：

- 用 `subprocess.Popen` + `text=True, bufsize=1`（line-buffered）
- stdin/stdout 是阻塞的，**不要用 select**（Windows 兼容性差），直接顺序读写
- 健康检查：每 100 次 submit 调一次 `_health_check()`，方法是发 `{"command":"ping"}`，5 秒内没回 `{"pong":true}` 就重启该 worker

#### C.5 `nalana_eval/workers/simple_runner.py`

调 `subprocess.run` 启动 single_run.py，超时 60 秒。

#### C.6 `nalana_eval/csv_db.py`

按 `CSV_SCHEMA.md` 的字段实现。注意：

- 用 `csv.DictWriter` 不是手拼字符串
- 先 `_ensure_files()` 检查文件存在，不存在就写 header
- `query_*` 用 `csv.DictReader` 读全部行进内存（CSV 文件不会大到放不下；如果担心，未来切 SQLite）

#### C.7 `nalana_eval/reporting.py`

按 `ARCHITECTURE.md` 第 2.12 节实现。**关键技巧**：

- 用 `string.Template` 或 jinja2（更灵活）渲染 markdown
- HUMAN_REVIEW_BLOCK 是 HTML 注释 `<!-- ... -->`，markdown 不会渲染
- screenshot 路径用相对路径 `screenshots/...`，不是绝对路径

#### C.8 `nalana_eval/harness.py`

最复杂的模块。按 `ARCHITECTURE.md` 第 2.14 节实现。建议子函数拆分：

```python
def run() -> List[BenchmarkRun]:
    for runner in self.runners:
        yield self._run_single_model(runner)

def _run_single_model(self, runner) -> BenchmarkRun: ...
def _run_single_case(self, runner, case, attempt_idx) -> AttemptArtifact: ...
def _run_honeypot(self, runner, attempts_so_far): ...
def _sample_cases(self, suite, n_cases, distributions) -> List[TestCaseCard]: ...
def _build_benchmark_run(...) -> BenchmarkRun: ...
```

`_sample_cases` 按 `difficulty_dist` 加权采样，用拒绝采样或加权随机。

---

### Phase D：CLI + 周边

#### D.1 `nalana_eval/cli.py`

argparse 子命令架构。子命令路由到对应模块。详见 `ARCHITECTURE.md` 第 2.1 节。

#### D.2 `nalana_eval/history.py`

读 `db/runs.csv`，输出 ASCII 表 / 折线 / matplotlib 图。

ASCII 折线参考 `plotille` 或简单自实现：

```python
def render_ascii_sparkline(values: List[float], width: int = 40) -> str:
    """█▇▆▅▄▃▂▁ 风格的稀疏折线。"""
```

#### D.3 `nalana_eval/review.py`

正则解析 markdown 里的 `<!-- HUMAN_REVIEW_BLOCK:... -->` 块：

```python
HUMAN_REVIEW_PATTERN = re.compile(
    r"<!-- HUMAN_REVIEW_BLOCK:([^:]+):attempt_(\d+)\n(.*?)\nEND_HUMAN_REVIEW_BLOCK -->",
    re.DOTALL,
)
```

每个匹配解析 YAML-like 字段（`key: value`），调 `csv_db.update_human_override()`。

#### D.4 `calibration/calibrate.py`

详见 `calibration/README.md`。流程：

1. 读 `calibration/reference_images/<style>/<image>.png`（每个 style 文件夹一组参考图）
2. 对每张图调 judge.judge()（伪造一个 case，style_intent.style = 该 style）
3. 聚合成报告：每个 style 的均分 / stddev / 跨风格偏差
4. 写 `calibration/baseline_results/<judge_model>_<timestamp>.json`

#### D.5 `fixtures/synthetic/generate_cases.py`

参考现有 `Nalana-datasc/testing/benchmark/synthetic_ground_truth.py` 思路，但产出 v3.0 约束格式。

模板化：每个 TaskFamily 一个生成函数，组合 primitive × color × size 出几百条 case。

#### D.6 `fixtures/starter_v3/*.json`

手写 ~30 条覆盖 6 个 category × 3 个 difficulty。每个 JSON 文件按 category 分组：

```
fixtures/starter_v3/
├── object_creation.json
├── transformations.json
├── materials.json
├── compositional.json
├── ambiguous.json
└── safety.json
```

每个文件是 `TestSuite` 格式（含 `suite_id` + `cases` 数组）。

---

### Phase E：测试

#### E.1 单元测试

每个模块对应一个 `test_<module>.py`。覆盖：

- 正常路径
- 边界值
- 错误路径（外部 API 失败、JSON 损坏、文件不存在）

用 `pytest --cov=nalana_eval` 看覆盖率，目标 80%+。

#### E.2 端到端 smoke test

`tests/test_e2e_smoke.py`：

```python
def test_e2e_with_mock_llm_and_mock_blender(tmp_path):
    """5 个 case + MockRunner + 模拟 worker，验证全 pipeline 跑通。"""
    suite = load_test_fixture("tests/fixtures/smoke_5_cases.json")
    runner = MockRunner(payload_file="tests/fixtures/mock_llm_responses.json")
    # 用 stub worker pool，return 预录的 snapshot/screenshot
    pool = StubWorkerPool(...)
    harness = Harness(suite, [runner], pool, ...)
    runs = list(harness.run())

    assert len(runs) == 1
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "screenshots/").is_dir()
    # 验证 CSV 写入
    assert os.path.exists("db/runs.csv")
```

#### E.3 Blender 集成测试（可选，需要 Blender）

```python
@pytest.mark.skipif(not has_blender(), reason="needs blender")
def test_real_blender_worker():
    """用真实 Blender 跑 1 个 case，验证 dispatcher + screenshot 都正常。"""
```

---

### Phase F：打包

#### F.1 `requirements.txt`

```
pydantic>=2.0
openai>=1.0
anthropic>=0.18
google-genai>=0.3
Pillow>=10.0
matplotlib>=3.7         # 可选，用于 history --plot
pytest>=7.0
pytest-cov>=4.0
python-dotenv>=1.0
```

#### F.2 `pyproject.toml`

```toml
[project]
name = "nalana-eval"
version = "3.0.0"
requires-python = ">=3.10"

[project.scripts]
nalana-eval = "nalana_eval.cli:main"
```

setuptools entry point 让 `nalana-eval ...` 直接可用。

---

## 3. 关键决策一览（不要再改）

| 决策 | 选择 | 文档引用 |
|---|---|---|
| 评测系统是否复用 Nalana XML-RPC | **不复用**，独立 subprocess | DESIGN.md §5.3 |
| LLM 输出格式 | JSON only（暂时不支持 Python 代码） | 用户确认 |
| 默认 Blender 执行模式 | Worker pool + stdin/stdout | DESIGN.md §5.2 |
| 截图渲染引擎 | Workbench 800×600 PNG | DESIGN.md §5.4 |
| Pass@k 默认值 | k=3，CLI 可配 | 用户确认 |
| Judge 评分次数 | N=3，取中位数 | DESIGN.md §4.3 步骤 4 |
| Judge 是否决定 pass/fail | **永不决定**，只软信号 | ARCHITECTURE.md §4.3 |
| v2.0 fixtures 处理 | 留作 L1 legacy 单元测试 | DESIGN.md §2.1 |
| 数据库格式 | CSV（appendix-only） | DESIGN.md §7.2 |
| 人审反馈通道 | report.md 里 HUMAN_REVIEW_BLOCK → review --collect | DESIGN.md §7.3 |
| 输出位置 | 全部写到 /Users/ianian/Nalana-eval/ | 用户确认 |

---

## 4. 别踩的坑（来自前辈血泪）

1. **不要在 worker 进程里用 print 调试**——它会污染 stdin/stdout 协议。用 `sys.stderr.write(...)` 或 logging 到文件。

2. **不要用 `bpy.ops.screen.screenshot()`**——它在 `--background` 模式下完全失效。必须用 `bpy.ops.render.render(write_still=True)`。

3. **不要假设场景里有相机**——starter cases 的 `initial_scene` 大多没相机。screenshot 函数必须能在没相机时自己创建。

4. **不要把 LLM raw output 直接喂给 dispatcher**——必须先经过 `contracts.normalize_model_output()` 走 allowlist 校验。否则 LLM 让你 `bpy.ops.wm.quit_blender()` 你就跑了。

5. **不要在 OpenAI runner 里漏掉 `response_format={"type":"json_object"}`**——不强制 JSON 时模型经常回复 "Here's the JSON: {...}" 加 prose，PARSE_ERROR 飙升。

6. **不要用 Anthropic 的 `response_format`**——Claude 不支持这个参数。靠 system prompt 的 "Output only JSON" 强制。

7. **不要让 worker pool 共享 stdout buffer**——每个 worker 必须有独立的 PIPE。否则不同 worker 的 JSON 会撞在一起，stdout 解析直接崩。

8. **不要在 simple_mode 里复用 worker_loop.py**——while loop 会无限等 stdin，single_run.py 是单次跑完就退出的简化版。

9. **不要在 dispatcher.py 里 import pydantic**——它在 Blender 进程内运行，Blender 的 Python 没装 pydantic。传 dict 进去。

10. **CSV 写入注意 Windows 换行**：`csv.DictWriter(f, ..., lineterminator='\n')` 强制 Unix 换行，避免 CRLF 污染 git diff。

---

## 5. 验证策略：写完 X 就跑 Y

| 写完 | 立刻跑 |
|---|---|
| `schema.py` | `pytest tests/test_schema.py` |
| `contracts.py` | `pytest tests/test_contracts.py` |
| `dispatcher.py` | `blender --background --python tests/blender_smoke/test_dispatcher_in_blender.py` |
| `screenshot.py` | 同上，验证能出 PNG |
| `evaluator.py` | `pytest tests/test_evaluator.py` |
| `judge.py` | `pytest tests/test_judge.py`（用 mock LLM） |
| 任何 runner | mock 测 + 真实 API 一个 1-case smoke |
| `worker_loop.py` + `pool.py` | 跑 5 case 端到端（用 MockRunner） |
| `harness.py` | `tests/test_e2e_smoke.py` |
| `cli.py` | `python -m nalana_eval.cli --cases 5 --models mock --simple-mode` |
| `reporting.py` | 跑完 5 case 看 report.md 在浏览器/编辑器渲染正常 |
| 全部 | 跑 30 case 真实 LLM smoke、看 report 美观度、跑 history 看 CSV 没坏 |

**永远不要**写完一大坨代码再统一测——bug 累积起来定位灾难。

---

## 6. 提交节奏建议

按 Phase 提 commit / PR：

- Commit A：Phase A（schema 层）+ tests 通过
- Commit B：Phase B（Blender 端）+ Blender smoke 通过
- Commit C：Phase C（评测端）+ E2E smoke 通过
- Commit D：Phase D（CLI + 周边）+ 真实 5-case smoke 通过
- Commit E：Phase E（完整测试套件）+ pytest 80% 覆盖率
- Commit F：Phase F（打包）+ `pip install -e .` 可用、`nalana-eval --help` 显示帮助

---

## 7. 你应该问用户什么问题

如果遇到下列情况，**停下来问用户**，不要自行决定：

1. 某个 starter case 的硬约束怎么写最合理（半径范围、bbox 边界）
2. system prompt 里要不要加 few-shot 例子
3. 判官 prompt 改动后校准集偏差怎么解读
4. 出现 v3.0 schema 字段不够用的情况（比如 case 想表达"必须不包含某种对象"）
5. CSV schema 有字段我们没考虑到（产品端有新埋点要落库）

**不要**自行扩展 schema 或改判官 prompt——这些是产品决策。

---

## 8. 当前 Cowork 阶段已经决定但还没写代码的事

- starter_v3 cases 的具体内容**没写**——只写了模板。Phase D.6 你来手写约 30 条
- `prompts/eval_default.md` 等 prompt 文件 Cowork 里写了，**直接用**，不要改
- Mock LLM 的 fixture（`tests/fixtures/mock_llm_responses.json`）**没写**——Phase E 你需要造

---

## 9. 环境变量 / 依赖外部状态

```
OPENAI_API_KEY        # OpenAI runner
ANTHROPIC_API_KEY     # Anthropic runner
GOOGLE_API_KEY        # Gemini runner
BLENDER_BIN           # 可选，默认 'blender'
NALANA_EVAL_RUNTIME_PATH  # worker_loop 用，指向 nalana_eval/ 包路径
NALANA_EVAL_DEBUG=1   # 可选，开启详细日志
```

---

## 10. 收工标准（DoD）

整套系统算实现完成，要满足：

- [ ] `pytest` 全绿，覆盖率 ≥ 80%
- [ ] `python -m nalana_eval.cli --cases 5 --models mock --simple-mode` 跑通
- [ ] `python -m nalana_eval.cli --cases 5 --models gpt-5 --simple-mode` 跑通（真实 API）
- [ ] `python -m nalana_eval.cli --cases 30 --models gpt-5 --workers 4` 跑通（worker pool）
- [ ] `report.md` 在 GitHub / VS Code 渲染美观
- [ ] `db/runs.csv` 在 Excel 打开正常
- [ ] `python -m nalana_eval.cli history --model gpt-5 --last 3` 输出正常
- [ ] `python -m nalana_eval.cli review --collect <md>` 能解析 HUMAN_REVIEW_BLOCK
- [ ] `python -m nalana_eval.cli calibrate --judge-model gpt-4o` 跑通
- [ ] README + 所有 docs/*.md 链接没断
- [ ] `pip install -e .` 后 `nalana-eval --help` 可用

---

**Brief 结束。祝你顺利接力。**
