# Nalana 评测系统：代码层架构

> 本文档面向**实现者和维护者**。讲清楚：每个模块做什么、模块之间怎么通信、关键数据流在哪里。

---

## 1. 一张图：模块依赖

```
                          ┌──────────────┐
                          │   cli.py     │ ← 用户入口
                          └──────┬───────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
        ┌──────────┐      ┌──────────┐       ┌──────────┐
        │  harness │      │ history  │       │  review  │
        │   .py    │      │   .py    │       │   .py    │
        └─────┬────┘      └─────┬────┘       └────┬─────┘
              │                 │                  │
              │                 │                  │
   ┌──────────┼─────────────────┼──────────────────┼─────────────┐
   │          │                 │                  │             │
   ▼          ▼                 ▼                  ▼             ▼
┌──────┐ ┌─────────┐      ┌──────────┐      ┌──────────┐  ┌──────────┐
│schema│ │runners/ │      │ workers/ │      │evaluator │  │  judge   │
│ .py  │ │  *.py   │      │  pool.py │      │   .py    │  │   .py    │
└──┬───┘ └────┬────┘      │worker_   │      └────┬─────┘  └─────┬────┘
   │          │           │ loop.py  │           │              │
   │          │           │simple_   │           │              │
   │          │           │runner.py │           │              │
   │          │           └────┬─────┘           │              │
   │          │                │                 │              │
   │          ▼                ▼                 │              │
   │     ┌─────────┐     ┌──────────────┐        │              │
   │     │contracts│     │ dispatcher   │        │              │
   │     │  .py    │────▶│   .py        │        │              │
   │     └─────────┘     │              │        │              │
   │                     │ executor.py  │        │              │
   │                     │              │        │              │
   │                     │scene_capture │        │              │
   │                     │  .py         │        │              │
   │                     │              │        │              │
   │                     │screenshot.py │        │              │
   │                     └──────┬───────┘        │              │
   │                            │                │              │
   │                            ▼                │              │
   │                     ┌──────────────┐        │              │
   └────────────────────▶│  reporting   │◀───────┘              │
                         │    .py       │◀──────────────────────┘
                         └──────┬───────┘
                                │
                                ▼
                         ┌──────────────┐
                         │  csv_db.py   │
                         └──────────────┘

   依赖方向（箭头）：A → B 表示 A 调用 B 的接口；B 不知道 A 的存在。
```

---

## 2. 模块清单（按调用顺序）

### 2.1 `cli.py`：唯一对外入口

**职责**：解析命令行参数，分发到子命令（`benchmark` / `history` / `review` / `calibrate`）。

**核心函数**：

```python
def main():
    parser = argparse.ArgumentParser(prog="nalana-eval")
    sub = parser.add_subparsers(dest="command")
    add_benchmark_parser(sub)   # 默认主命令（无 sub 时）
    add_history_parser(sub)
    add_review_parser(sub)
    add_calibrate_parser(sub)
    add_db_parser(sub)
    args = parser.parse_args()
    args.func(args)
```

**关键参数解析**：

- `--difficulty-dist short:0.4,medium:0.4,long:0.2` → `dict[str, float]`
- `--models gpt-5,claude-sonnet-4-6` → `list[str]`
- 加载 `.env` → `os.environ`

---

### 2.2 `schema.py`：v3.0 数据模型（pydantic）

**职责**：定义所有 JSON 格式的数据类，用 pydantic 做严格校验。

**关键类**（详细字段见 `TEST_CASE_AUTHORING.md` 和 `CSV_SCHEMA.md`）：

```python
class Category(str, Enum): ...
class Difficulty(str, Enum): ...      # SHORT / MEDIUM / LONG
class TaskFamily(str, Enum): ...
class FailureClass(str, Enum): ...    # PARSE_ERROR / EXECUTION_ERROR / CONSTRAINT_FAILED ...

class HardConstraints(BaseModel):
    mesh_object_count: Optional[CountRange] = None
    required_object_types: List[str] = []
    required_named_objects: List[str] = []
    bounding_boxes: List[BoundingBoxConstraint] = []
    positions: List[PositionConstraint] = []
    relative_positions: List[RelativePositionConstraint] = []
    materials: List[MaterialConstraint] = []
    scene_mutation: Optional[SceneMutationPolicy] = None

class TopologyPolicy(BaseModel):
    manifold_required: bool = False
    quad_ratio_min: float = 0.0
    max_face_count: Optional[int] = None
    max_vertex_count: Optional[int] = None

class SoftConstraint(BaseModel):
    name: str
    metric: SoftMetric
    direction: SoftDirection           # exact / min / max
    target: float
    tolerance: float = 0.0
    weight: float = 1.0

class StyleIntent(BaseModel):
    explicit: bool = False
    style: Optional[str] = None
    concept: Optional[str] = None
    concept_aliases: List[str] = []
    acceptable_styles: List[str] = []

class JudgePolicy(str, Enum):
    SKIP = "skip"
    SCORE = "score"
    AUDIT_ONLY = "audit_only"

class TestCaseCard(BaseModel):
    fixture_version: str = "3.0"
    id: str
    category: Category
    difficulty: Difficulty
    task_family: TaskFamily
    prompt_variants: List[str]                  # min 1, recommended 3-5
    initial_scene: InitialScene
    hard_constraints: HardConstraints
    topology_policy: TopologyPolicy
    soft_constraints: List[SoftConstraint] = []
    style_intent: StyleIntent
    judge_policy: JudgePolicy = JudgePolicy.SCORE
    artifact_policy: ArtifactPolicy

class AttemptArtifact(BaseModel):
    case_id: str
    attempt_index: int
    model_id: str
    prompt_used: str
    raw_output: Any
    normalized_output: List[NormalizedStep]
    parse_success: bool
    safety_success: bool
    execution_success: bool
    passed_hard_constraints: bool
    passed_topology: bool
    soft_score: float                  # 0-1
    pass_overall: bool                 # = hard ∧ topology
    failure_class: FailureClass
    failure_reason: Optional[str]
    scene_snapshot: SceneSnapshot
    judge_result: Optional[JudgeResult]
    screenshot_path: str
    scene_stats_path: str
    model_latency_ms: float
    execution_latency_ms: float
    cost_usd: float

class JudgeResult(BaseModel):
    detected_style: str
    detected_concept: str
    style_alignment_pass: bool
    concept_alignment_pass: bool
    semantic: float                    # median of N runs
    aesthetic: float
    professional: float
    stddev: float                      # variance across runs
    judged_under_standard: str
    reasoning: str
    confidence: float
    raw_responses: List[dict]          # all N raw judge calls

class TestSuite(BaseModel):
    suite_id: str
    fixture_version: str
    cases: List[TestCaseCard]
    @classmethod
    def from_json_or_dir(cls, path: str) -> "TestSuite": ...
```

**重要约定**：所有 pydantic 模型 `extra="forbid"`，未知字段直接报错——保证 schema 不漂移。

---

### 2.3 `legacy_schema.py`：v2.0 schema（原样保留）

直接 fork 现有 `Nalana-eval/schema.py`（v2.0），改包名引用即可。**不要修改字段**——legacy 套件需要保持向后兼容。

---

### 2.4 `contracts.py`：JSON 规范化 + safety allowlist

**职责**：从现有 `Nalana-datasc/testing/benchmark/contracts.py` 移植。把 LLM 返回的三种 contract（LEGACY_OPS / TYPED_COMMANDS / NORMALIZED）统一规范化为 `NormalizedStep` 列表。

**关键函数**：

```python
def normalize_model_output(raw: Any) -> Tuple[List[NormalizedStep], OutputContract]:
    """LLM 原始输出 → 规范化的 step 列表 + 检测到的 contract。"""

def canonicalize_step(kind: StepKind, args: dict) -> NormalizedStep:
    """对单个 step 做参数校验、类型转换、范围检查。"""

# Allowlist：定义在常量里，所有未出现的 bpy.ops 一律拒绝
ALLOWED_PRIMITIVES = {"CUBE", "UV_SPHERE", "ICO_SPHERE", ...}
ALLOWED_MODES = {"OBJECT", "EDIT"}
```

**安全设计**：参数边界检查（如 `radius` 必须 > 0、`segments` 在 [3, 256]）防止 LLM 触发 Blender 卡死或资源耗尽。

---

### 2.5 `runners/`：LLM 调用适配器

每个 runner 实现 `BaseModelRunner`：

```python
# runners/base.py
class BaseModelRunner(ABC):
    def __init__(self, model_id: str, system_prompt: str, **kwargs): ...

    def invoke(self, case: TestCaseCard, prompt_variant: str, attempt_index: int) -> ModelInvocation:
        """完整调用：build_prompt → API call → 解析 → 计算 latency/cost。"""
        prompt = self.build_prompt(case, prompt_variant)
        started = time.perf_counter()
        try:
            raw = self._generate(prompt, temperature=self.temperature, seed=...)
        except Exception as e:
            return ModelInvocation(parse_error=str(e), ...)
        latency = (time.perf_counter() - started) * 1000
        normalized, contract = normalize_model_output(raw)
        return ModelInvocation(raw_output=raw, normalized_output=normalized, ...)

    @abstractmethod
    def _generate(self, prompt: str, **kwargs) -> Any:
        """子类实现：调实际 API。"""

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """根据模型定价表算成本。"""
```

**具体子类**：

| 文件 | 模型 | API 调用方式 |
|---|---|---|
| `openai_runner.py` | gpt-5, gpt-4o, gpt-4-turbo | `openai.chat.completions.create(response_format={"type":"json_object"})` |
| `anthropic_runner.py` | claude-sonnet-4-6, claude-opus-4-6 | `anthropic.messages.create()` + 强制 JSON 输出 |
| `gemini_runner.py` | gemini-2.5-pro | `google.genai.GenerativeModel` |
| `mock_runner.py` | mock | 用预录的 JSON 返回，**用于单元测试** |

**统一行为**：
- 自动指数退避重试（429/5xx）
- 调用前校验 API key 存在性
- 记录 cost（token 数 × 单价）

---

### 2.6 `workers/`：Blender 执行后端

**两种模式**：

#### 2.6.1 `workers/pool.py`（默认 worker pool）

```python
class WorkerPool:
    def __init__(self, n_workers: int, blender_bin: str): ...

    def start(self):
        """启动 N 个 blender --background --python worker_loop.py 进程。"""
        for i in range(self.n_workers):
            proc = subprocess.Popen(
                [self.blender_bin, "--background", "--python", "worker_loop.py"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
            self.workers.append(WorkerHandle(proc, ...))

    def submit(self, case_payload: dict) -> dict:
        """阻塞式提交 case，从空闲 worker 拿结果。"""
        worker = self._next_idle()
        worker.proc.stdin.write(json.dumps(case_payload) + "\n")
        worker.proc.stdin.flush()
        result_line = worker.proc.stdout.readline()
        return json.loads(result_line)

    def health_check(self):
        """每 100 个 case 调用一次，重启内存涨过阈值的 worker。"""

    def shutdown(self):
        for w in self.workers:
            w.proc.stdin.write('{"command":"exit"}\n')
            w.proc.wait(timeout=5)
```

**通信协议**：JSON over stdin/stdout，每行一条消息。

请求消息：
```json
{"command":"run_case","case":<TestCaseCard>,"normalized_steps":[...],"output_dir":"/path"}
```

响应消息：
```json
{"ok":true,"snapshot":<SceneSnapshot>,"screenshot_path":"...","scene_stats_path":"...","execution_latency_ms":234.5}
```

#### 2.6.2 `workers/worker_loop.py`（Blender 端常驻脚本）

```python
# 只在 Blender 内运行，不能被外部 python 直接 import
import sys, json, bpy

# 这个 import 会从 zip / 路径里找 dispatcher 等模块
sys.path.insert(0, BLENDER_RUNTIME_PATH)
from nalana_eval_runtime import dispatcher, scene_capture, screenshot

while True:
    line = sys.stdin.readline()
    if not line:
        break
    msg = json.loads(line)
    if msg["command"] == "exit":
        break
    if msg["command"] == "run_case":
        result = run_one_case(msg)
        sys.stdout.write(json.dumps(result) + "\n")
        sys.stdout.flush()


def run_one_case(msg):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    case = msg["case"]
    steps = msg["normalized_steps"]

    # 1. 重建初始场景
    dispatcher.reset_scene(case["initial_scene"])

    # 2. 执行 steps
    try:
        dispatcher.execute_normalized_steps(steps)
        execution_success = True
        error = None
    except Exception as e:
        execution_success = False
        error = str(e)

    # 3. 抓 snapshot
    snapshot = scene_capture.capture()

    # 4. 渲染截图
    screenshot_path = msg["output_dir"] + f"/{case['id']}_attempt_{msg['attempt_index']}.png"
    screenshot.render_scene_to_png(screenshot_path, resolution=(800, 600))
    # 同时生成缩略图
    screenshot.make_thumbnail(screenshot_path)

    return {
        "ok": execution_success,
        "error": error,
        "snapshot": snapshot.model_dump(),
        "screenshot_path": screenshot_path,
        ...
    }
```

#### 2.6.3 `workers/simple_runner.py`（`--simple-mode` 入口）

每 case 一次 subprocess。把 `worker_loop.py` 改造成单次跑：

```python
# 调用方（harness）
def run_case_simple(case_payload, blender_bin):
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = f"{tmpdir}/input.json"
        output_path = f"{tmpdir}/output.json"
        with open(input_path, "w") as f:
            json.dump(case_payload, f)
        subprocess.run([
            blender_bin, "--background", "--python", "single_run.py",
            "--", input_path, output_path,
        ], check=True, timeout=60)
        return json.load(open(output_path))
```

---

### 2.7 `dispatcher.py`：JSON → bpy.ops 翻译器

**只在 Blender 进程内运行**（依赖 `bpy`）。

```python
import bpy, bmesh

def reset_scene(initial_scene: dict):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if initial_scene.get("objects"):
        for seed in initial_scene["objects"]:
            seed_object(seed)
    if initial_scene.get("active"):
        bpy.context.view_layer.objects.active = bpy.data.objects[initial_scene["active"]]

def execute_normalized_steps(steps: List[dict]):
    """逐个 step 执行；任何一步报错就抛异常。"""
    for step in steps:
        dispatch_one_step(step)

def dispatch_one_step(step: dict):
    kind = step["kind"]
    args = step["args"]
    if kind == "ADD_MESH":
        primitive = args["primitive"]
        if primitive == "CUBE":
            bpy.ops.mesh.primitive_cube_add(**{k:v for k,v in args.items() if k != "primitive"})
        # ... 其他 primitive
    elif kind == "SET_MODE":
        bpy.ops.object.mode_set(mode=args["mode"])
    # ... 其他 step kind
```

**架构原则**：dispatcher 是评测系统**自己的**，**不依赖 Nalana 生产的 XML-RPC**。

---

### 2.8 `scene_capture.py`：场景统计抓取

```python
def capture() -> SceneSnapshot:
    mesh_objects = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        face_sizes = Counter(len(face.verts) for face in bm.faces)
        manifold = all(edge.is_manifold for edge in bm.edges)
        # bbox
        bbox_world = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        bm.free()
        mesh_objects.append(SceneMeshSnapshot(...))
    return SceneSnapshot(mesh_objects=mesh_objects, ...)
```

**输出字段**：vertex_count、face_count、face_sizes（dict: 边数 → 数量）、manifold、bbox（min/max）、location/rotation/scale、materials（含 base_color）。

---

### 2.9 `screenshot.py`：渲染截图

```python
def render_scene_to_png(output_path: str, resolution=(800, 600)):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.filepath = output_path
    scene.render.image_settings.file_format = 'PNG'

    place_camera_iso(scene)
    setup_workbench_lighting(scene)

    bpy.ops.render.render(write_still=True)


def place_camera_iso(scene):
    """根据所有 mesh 对象的合并 bbox，放置等距相机。"""
    mesh_objects = [o for o in bpy.data.objects if o.type == "MESH"]
    if not mesh_objects:
        # 空场景：放默认相机
        scene.camera = ensure_default_camera()
        return
    all_corners = [obj.matrix_world @ Vector(c) for obj in mesh_objects for c in obj.bound_box]
    center = sum(all_corners, Vector()) / len(all_corners)
    max_dim = max(
        max(c.x for c in all_corners) - min(c.x for c in all_corners),
        max(c.y for c in all_corners) - min(c.y for c in all_corners),
        max(c.z for c in all_corners) - min(c.z for c in all_corners),
        0.1,
    )
    distance = max_dim * 2.5
    cam = ensure_default_camera()
    cam.location = center + Vector((distance, -distance, distance * 0.7))
    cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam


def make_thumbnail(png_path: str, size=(512, 384)):
    """从 PIL 出缩略图，保存到 _thumb.png。"""
    from PIL import Image
    img = Image.open(png_path)
    img.thumbnail(size)
    thumb_path = png_path.replace(".png", "_thumb.png")
    img.save(thumb_path)
```

---

### 2.10 `evaluator.py`：约束评估（L2 主逻辑）

```python
class ConstraintEvaluator:
    def evaluate(
        self,
        case: TestCaseCard,
        snapshot: SceneSnapshot,
        execution_success: bool,
    ) -> EvaluationResult:
        """返回 hard/topology/soft 三层结果。"""
        if not execution_success:
            return EvaluationResult(
                hard_pass=False, topology_pass=False, soft_score=0.0,
                failure_class=FailureClass.EXECUTION_ERROR,
            )

        hard_pass, hard_violations = self._check_hard(case.hard_constraints, snapshot)
        topo_pass, topo_violations = self._check_topology(case.topology_policy, snapshot)
        soft_score = self._score_soft(case.soft_constraints, snapshot)

        return EvaluationResult(
            hard_pass=hard_pass,
            topology_pass=topo_pass,
            soft_score=soft_score,
            hard_violations=hard_violations,
            topology_violations=topo_violations,
            failure_class=...,
        )

    def _check_hard(self, hc: HardConstraints, snap) -> Tuple[bool, List[str]]:
        violations = []
        if hc.mesh_object_count and not hc.mesh_object_count.matches(snap.total_mesh_objects):
            violations.append(f"mesh_object_count: ...")
        # bbox checks, material checks, position checks ...
        return (len(violations) == 0, violations)

    def _check_topology(self, tp: TopologyPolicy, snap) -> Tuple[bool, List[str]]: ...
    def _score_soft(self, soft: List[SoftConstraint], snap) -> float: ...
```

每个约束类型（bbox / material / position / relative_position）有专门的校验函数。

---

### 2.11 `judge.py`：LLM-as-Judge

详细见第 3 章和 `prompts/judge_prompt.md`。

```python
class JudgeRunner:
    def __init__(self, judge_model: str, num_runs: int = 3, budget_usd: float = 10.0): ...

    def judge(
        self,
        case: TestCaseCard,
        screenshot_path: str,
        prompt_used: str,
    ) -> Optional[JudgeResult]:
        """如果 case.judge_policy == SKIP，返回 None。"""
        if case.judge_policy == JudgePolicy.SKIP:
            return None
        if self._budget_exhausted():
            return None  # report 里标 "budget exceeded"

        # 检查 cache
        cache_key = self._compute_cache_key(prompt_used, screenshot_path)
        if cached := self.cache.get(cache_key):
            return cached

        # 跑 N 次（默认 3）
        raw_responses = []
        for _ in range(self.num_runs):
            raw = self._call_judge(case, screenshot_path, prompt_used)
            raw_responses.append(raw)
            self._add_cost(raw)

        # 合并：取中位数 + 计算 stddev
        result = self._aggregate(raw_responses)
        self.cache.set(cache_key, result)
        return result

    def _call_judge(self, case, screenshot_path, prompt_used) -> dict:
        """发一次多模态 API 调用。"""
        messages = build_judge_messages(case, screenshot_path, prompt_used)
        return call_multimodal_llm(self.judge_model, messages)
```

**关键实现要点**：
- 缓存用 SQLite（`db/judge_cache.sqlite`），key 是 `sha256(prompt + image_pixels)`，value 是 JudgeResult JSON
- 预算超额时返回 None，**不抛异常**——让 run 继续
- 多模态调用：图片以 base64 inline 发送，节省一次上传

---

### 2.12 `reporting.py`：report.md / report.json 生成

```python
class BenchmarkReporter:
    def write_run(self, run: BenchmarkRun, output_dir: str):
        os.makedirs(output_dir, exist_ok=True)
        self._write_json(run, f"{output_dir}/report.json")
        self._write_markdown(run, f"{output_dir}/report.md")
        self._write_failures_jsonl(run, f"{output_dir}/failures.jsonl")
        self._write_config(run.config, f"{output_dir}/config.json")
        # 写 baseline_delta.json（如果能找到上次同模型 run）
        prev = self._find_previous_run(run.model_id)
        if prev:
            delta = compute_delta(run, prev)
            self._write_json(delta, f"{output_dir}/baseline_delta.json")

    def _write_markdown(self, run, path):
        sections = [
            self._render_header(run),
            self._render_executive_summary(run),
            self._render_distribution(run),
            self._render_breakdown(run),
            self._render_failure_reasons(run),
            self._render_sample_cases(run),    # 含 HUMAN_REVIEW_BLOCK
            self._render_baseline_delta(run),
            self._render_judge_reliability(run),
        ]
        with open(path, "w") as f:
            f.write("\n\n".join(sections))
```

**HUMAN_REVIEW_BLOCK 模板**（每个有判官分的 case 都嵌一个）：

```markdown
<!-- HUMAN_REVIEW_BLOCK:{case_id}:attempt_{n}
override: pending
corrected_semantic:
corrected_aesthetic:
corrected_professional:
reviewer:
note:
END_HUMAN_REVIEW_BLOCK -->
```

---

### 2.13 `csv_db.py`：CSV 数据库

```python
RUNS_CSV = "db/runs.csv"
ATTEMPTS_CSV = "db/attempts.csv"
JUDGE_VS_HUMAN_CSV = "db/judge_vs_human.csv"

RUNS_FIELDS = [...]            # 见 CSV_SCHEMA.md
ATTEMPTS_FIELDS = [...]

class CsvDb:
    def __init__(self, db_dir: str):
        self.db_dir = db_dir
        self._ensure_files()

    def append_run(self, run: BenchmarkRun): ...
    def append_attempts(self, attempts: List[AttemptArtifact]): ...
    def query_runs(self, **filters) -> List[dict]: ...
    def query_attempts(self, **filters) -> List[dict]: ...
    def update_human_override(self, run_id, case_id, attempt_index, **fields): ...
```

写入策略：appendix-only，不修改历史行（保证审计性）。`update_human_override` 是唯一允许修改的字段族。

---

### 2.14 `harness.py`：主调度器（对应原 `test_harness.py`）

```python
class Harness:
    def __init__(self, suite, runners, worker_pool, evaluator, judge, reporter, csv_db, config):
        ...

    def run(self) -> List[BenchmarkRun]:
        results = []
        for runner in self.runners:
            results.append(self._run_single_model(runner))
        return results

    def _run_single_model(self, runner):
        run_id = uuid4().hex[:8]
        sampled_cases = sample_cases(self.suite, self.config.cases, self.config.distributions)
        attempts = []
        for case in sampled_cases:
            for attempt_idx in range(self.config.pass_at_k):
                prompt_variant = case.prompt_variants[attempt_idx % len(case.prompt_variants)]
                # 1. 调 LLM
                invocation = runner.invoke(case, prompt_variant, attempt_idx)
                # 2. Blender 执行
                exec_result = self.worker_pool.submit({
                    "case": case.dict(),
                    "normalized_steps": [s.dict() for s in invocation.normalized_output],
                    "attempt_index": attempt_idx,
                    "output_dir": self.run_folder,
                })
                # 3. 约束评估
                eval_result = self.evaluator.evaluate(case, exec_result["snapshot"], exec_result["ok"])
                # 4. 判官（可选）
                judge_result = self.judge.judge(case, exec_result["screenshot_path"], invocation.prompt) \
                    if self.judge else None
                # 5. 组装 attempt artifact
                attempts.append(AttemptArtifact(...))

            # honeypot 检测：每 10 个 case 插入 1 个
            if len(attempts) % (10 * self.config.pass_at_k) == 0:
                self._run_honeypot(runner, attempts)

        run = self._build_benchmark_run(run_id, runner, sampled_cases, attempts)
        self.reporter.write_run(run, self.run_folder)
        self.csv_db.append_run(run)
        self.csv_db.append_attempts(attempts)
        return run
```

---

## 3. 数据流：一个 case 的完整生命周期

以 `CV-OBJ-042 "创建一个红色的球体"` 为例：

```
1. cli.py 解析 --cases 200 --models gpt-5
   ↓
2. harness.py 加载 suite，按分布采样到 200 个 case，CV-OBJ-042 是其中一个
   ↓
3. harness 调用 runners/openai_runner.py.invoke(case, "创建红色球体", 0)
   ├─ build_prompt() 拼出完整 prompt（system + user + JSON contract guidance）
   ├─ openai.chat.completions.create(...) 返回 raw JSON
   └─ contracts.normalize_model_output(raw) → 规范化 step 列表
   ↓
4. harness 把 case + steps 提交给 workers/pool.py
   ├─ pool 找到空闲 worker，写入 stdin
   └─ Blender worker 收到 case：
       ├─ dispatcher.reset_scene(initial_scene)
       ├─ dispatcher.execute_normalized_steps(steps)  ← 调真实 bpy.ops
       ├─ scene_capture.capture() → SceneSnapshot
       └─ screenshot.render_scene_to_png() → PNG
   └─ worker 返回 result 到 pool 的 stdout
   ↓
5. harness 调 evaluator.evaluate(case, snapshot)
   ├─ 检查 hard_constraints：
   │   - mesh_object_count >= 1? ✓
   │   - bounding_box [3,3,3]–[5,5,5]? ✓
   │   - material color red (tol 0.2)? ✗ 实际灰色
   ├─ topology: manifold ✓, quad_ratio 0.0 (allowed) ✓
   └─ soft_score: 0.5（顶点数刚刚过 100）
   ↓
6. harness 调 judge.judge(case, screenshot_path, prompt)
   ├─ 检查 cache miss
   ├─ 调 GPT-4o 3 次（multimodal: base64 image + structured prompt）
   ├─ 取中位数: semantic=4, aesthetic=3, professional=3, stddev=0.5
   └─ judged_under_standard="geometric" (acceptable_styles 里推断)
   ↓
7. harness 组装 AttemptArtifact，写到 attempts 列表
   ↓
8. 全部 case 跑完 → reporting.py 写 report.md/json + screenshots/
   ↓
9. csv_db.py 追加一行到 runs.csv，N 行到 attempts.csv
   ↓
10. 用户看 report.md，发现判官给"灰色球体"的 semantic 打了 4 分
    ↓
11. 用户在 HUMAN_REVIEW_BLOCK 里改 override: disagree, corrected_semantic: 2
    ↓
12. 跑 nalana-eval review --collect → 写回 attempts.csv 的 judge_human_override
    ↓
13. 同步追加一行到 judge_vs_human.csv 用于长期学习
```

---

## 4. 关键架构原则（必须遵守）

### 4.1 "评测系统不依赖 Nalana 生产的 XML-RPC"

- 评测的 LLM 调用 **直接** 走 OpenAI/Anthropic/Google SDK
- 评测的 Blender 通信 **直接** 走 subprocess + stdin/stdout
- **不要** 复用 `Nalana-datasc/__init__.py` 里的 RPC server（端口 8765）

### 4.2 "确定性测试不进 benchmark 报告"

- `tests/` 里的 pytest 单元测试 **从不出现在 report.md 里**
- benchmark 关心的是模型表现，不是评测系统自身的 bug

### 4.3 "judge 永不决定 pass/fail"

- `pass_overall = passed_hard_constraints AND passed_topology`
- judge 分进 report 但不参与 pass_overall 的逻辑
- 这是 judge 偏见保护的最后一道闸门

### 4.4 "appendix-only 数据库"

- `db/runs.csv` / `attempts.csv` 只追加、不修改历史
- 唯一例外是人审 override 字段，且必须保留所有 reviewer 历史

### 4.5 "fixture_version 严格匹配"

- v3.0 用例进 v3.0 schema，v2.0 用例进 v2.0 schema
- 跨版本调用会报 `LegacySuiteError`

---

## 5. 性能目标（SLO）

| 指标 | 目标 | 测量方法 |
|---|---|---|
| 1000 用例 worker pool 模式总耗时 | < 10 分钟 | 8 worker、Workbench 渲染、平均 3 ops/case |
| 1000 用例 simple-mode 总耗时 | < 50 分钟 | 单 subprocess |
| 单 case 平均耗时（worker pool） | < 0.6 秒 | model call + execution + capture + screenshot |
| 单次 judge 调用 | < 2 秒 | GPT-4o multimodal |
| Report 生成 | < 5 秒 | 200 case |

不达标视为性能 bug，提 issue。

---

## 6. 错误处理矩阵

| 失败位置 | failure_class | report 里怎么标 | 是否计入失败统计 |
|---|---|---|---|
| LLM API 调用失败（超时/429） | `MODEL_ERROR` | "model unreachable, retried 3x" | 不计入（infrastructure） |
| LLM 返回非 JSON | `PARSE_ERROR` | "invalid JSON: ..." | 计入 |
| JSON schema 校验失败 | `PARSE_ERROR` | "schema mismatch: ..." | 计入 |
| 操作不在 allowlist | `SAFETY_BLOCKED` | "blocked op: ..." | 计入 |
| Blender 执行抛异常 | `EXECUTION_ERROR` | "bpy error: ..." | 计入 |
| 硬约束不满足 | `CONSTRAINT_FAILED` | "violations: [list]" | 计入 |
| 拓扑约束不满足 | `TOPOLOGY_FAILED` | "non-manifold edges: 5" | 计入 |
| Worker 卡死/超时 | `WORKER_TIMEOUT` | "worker hung, restarted" | 不计入（infrastructure） |
| 判官 API 失败 | (judge_result = None) | "judge unavailable" | 不影响 pass/fail |

---

## 7. 测试策略

详见 `IMPLEMENTATION_BRIEF.md` 第 5 节。

简版：

- `test_schema.py`：所有 pydantic 模型的边界值
- `test_contracts.py`：normalize 三种 contract、reject 危险操作
- `test_dispatcher.py`：在 mock bpy 下跑各 step kind
- `test_evaluator.py`：每种约束的 pass/fail 矩阵
- `test_judge.py`：mock LLM 返回值，验证 aggregate / cache / variance
- `test_csv_db.py`：append、query、override 回流
- `test_e2e_smoke.py`：mock LLM + mock Blender 跑 5 个 case 端到端

---

**架构文档结束。下一步看 `IMPLEMENTATION_BRIEF.md` 拿到逐文件实现规范。**
