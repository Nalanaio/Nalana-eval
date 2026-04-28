from __future__ import annotations

import json
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FIXTURE_VERSION = "3.0"
PROMPT_TEMPLATE_VERSION = "benchmark-constraint-eval-v1"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Category(str, Enum):
    OBJECT_CREATION = "Object Creation"
    TRANSFORMATIONS = "Transformations & Editing"
    MATERIALS = "Materials & Shading"
    COMPOSITIONAL = "Compositional-Creative"
    AMBIGUOUS = "Ambiguous/Contextual"
    ERROR_RECOVERY = "Error Recovery & Safety"


class Difficulty(str, Enum):
    SHORT = "Short"
    MEDIUM = "Medium"
    LONG = "Long"


class TaskFamily(str, Enum):
    PRIMITIVE_CREATION = "primitive_creation"
    PARAMETERIZED_PRIMITIVE_CREATION = "parameterized_primitive_creation"
    SEEDED_TRANSFORM_EDIT = "seeded_transform_edit"
    BEVEL_INSET_EXTRUDE = "bevel_inset_extrude"
    MATERIAL_COLOR_ASSIGNMENT = "material_color_assignment"
    CAMERA_ASSIGNMENT = "camera_assignment"
    SIMPLE_MULTI_OBJECT_COMPOSITION = "simple_multi_object_composition"
    SCENE_HYGIENE_SAFETY = "scene_hygiene_safety"
    OPEN_ENDED_CREATIVE = "open_ended_creative"


class StepKind(str, Enum):
    ADD_MESH = "ADD_MESH"
    SET_MODE = "SET_MODE"
    TRANSLATE = "TRANSLATE"
    SCALE = "SCALE"
    ROTATE = "ROTATE"
    BEVEL = "BEVEL"
    INSET = "INSET"
    EXTRUDE_REGION = "EXTRUDE_REGION"
    SET_CAMERA = "SET_CAMERA"
    SET_MATERIAL = "SET_MATERIAL"
    DELETE_ALL = "DELETE_ALL"
    SELECT_ALL = "SELECT_ALL"


class OutputContract(str, Enum):
    AUTO = "auto"
    NORMALIZED = "normalized"
    LEGACY_OPS = "legacy_ops"
    TYPED_COMMANDS = "typed_commands"


class FailureClass(str, Enum):
    NONE = "NONE"
    PARSE_ERROR = "PARSE_ERROR"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    CONSTRAINT_FAILED = "CONSTRAINT_FAILED"
    TOPOLOGY_FAILED = "TOPOLOGY_FAILED"
    MODEL_ERROR = "MODEL_ERROR"
    WORKER_TIMEOUT = "WORKER_TIMEOUT"


class JudgePolicy(str, Enum):
    SKIP = "skip"
    SCORE = "score"
    AUDIT_ONLY = "audit_only"


class SoftMetric(str, Enum):
    TOTAL_OBJECTS = "total_objects"
    TOTAL_MESH_OBJECTS = "total_mesh_objects"
    TOTAL_VERTICES = "total_vertices"
    TOTAL_FACES = "total_faces"
    QUAD_RATIO = "quad_ratio"
    NEW_OBJECT_COUNT = "new_object_count"


class SoftDirection(str, Enum):
    EXACT = "exact"
    MIN = "min"
    MAX = "max"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _coerce_vector(value: Any, *, length: int = 3) -> List[float]:
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"Expected a {length}-element vector, got {value!r}")
    coerced: List[float] = []
    for item in value:
        if not isinstance(item, (int, float)):
            raise ValueError(f"Vector values must be numeric, got {item!r}")
        coerced.append(float(item))
    return coerced


# ---------------------------------------------------------------------------
# Step types (shared with contracts.py and legacy)
# ---------------------------------------------------------------------------


class LegacyOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: str
    params: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _accept_kwargs_alias(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if "params" not in payload and "kwargs" in payload:
            payload["params"] = payload.pop("kwargs")
        payload.setdefault("params", {})
        return payload


class TypedCommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    args: Dict[str, Any] = Field(default_factory=dict)


class NormalizedStep(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: StepKind
    args: Dict[str, Any] = Field(default_factory=dict)

    def signature(self) -> Dict[str, Any]:
        return {"kind": self.kind.value, "args": self.args}

    def signature_hash(self) -> str:
        serialized = json.dumps(self.signature(), sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Scene seed / initial scene
# ---------------------------------------------------------------------------


class SceneSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primitive: str = "CUBE"
    name: Optional[str] = None
    location: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: List[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0])

    @field_validator("primitive")
    @classmethod
    def _normalize_primitive(cls, value: str) -> str:
        if not value:
            raise ValueError("Scene seed primitive must be non-empty")
        return str(value).upper()

    @field_validator("location", "rotation", "scale")
    @classmethod
    def _validate_vectors(cls, value: List[float]) -> List[float]:
        return _coerce_vector(value)


class InitialScene(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    active_object: Optional[str] = Field(default=None, alias="active")
    mode: str = "OBJECT"
    objects: List[SceneSeed] = Field(default_factory=list)

    @field_validator("mode")
    @classmethod
    def _normalize_mode(cls, value: str) -> str:
        return str(value or "OBJECT").upper()


# ---------------------------------------------------------------------------
# Hard constraint sub-models
# ---------------------------------------------------------------------------


class CountRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum: Optional[int] = Field(default=None, ge=0)
    maximum: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_range(self) -> "CountRange":
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError(f"minimum ({self.minimum}) > maximum ({self.maximum})")
        return self

    def matches(self, value: int) -> bool:
        if self.minimum is not None and value < self.minimum:
            return False
        if self.maximum is not None and value > self.maximum:
            return False
        return True


class BoundingBoxSizeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum: Optional[List[float]] = None
    maximum: Optional[List[float]] = None

    @field_validator("minimum", "maximum")
    @classmethod
    def _validate_vec3(cls, value: Optional[List[float]]) -> Optional[List[float]]:
        if value is not None:
            return _coerce_vector(value)
        return value


class BoundingBoxConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # "__scene__" = merged scene bbox, "*" = any mesh object, or named object
    target: str
    size_range: BoundingBoxSizeRange


class MaterialConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # "*" = any mesh, or named object
    target: str = "*"
    base_color: Optional[List[float]] = None
    tolerance: float = Field(default=0.2, ge=0.0, le=1.0)

    @field_validator("base_color")
    @classmethod
    def _validate_color(cls, value: Optional[List[float]]) -> Optional[List[float]]:
        if value is None:
            return value
        if isinstance(value, tuple):
            value = list(value)
        if not isinstance(value, list) or len(value) not in {3, 4}:
            raise ValueError("base_color must be a 3- or 4-element list")
        result = []
        for v in value:
            f = float(v)
            if not (0.0 <= f <= 1.0):
                raise ValueError(f"base_color channel {f} out of [0, 1] range")
            result.append(f)
        return result


class PositionConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str
    location: List[float]
    tolerance: float = Field(default=0.1, ge=0.0)

    @field_validator("location")
    @classmethod
    def _validate_loc(cls, value: List[float]) -> List[float]:
        return _coerce_vector(value)


class RelativePositionConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_a: str
    object_b: str
    # "above" | "below" | "left" | "right" | "front" | "back"
    relation: str
    tolerance: float = Field(default=0.1, ge=0.0)


class SceneMutationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preserve_seed_objects: bool = False


class HardConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mesh_object_count: Optional[CountRange] = None
    required_object_types: List[str] = Field(default_factory=list)
    required_named_objects: List[str] = Field(default_factory=list)
    bounding_boxes: List[BoundingBoxConstraint] = Field(default_factory=list)
    positions: List[PositionConstraint] = Field(default_factory=list)
    relative_positions: List[RelativePositionConstraint] = Field(default_factory=list)
    materials: List[MaterialConstraint] = Field(default_factory=list)
    scene_mutation: Optional[SceneMutationPolicy] = None


# ---------------------------------------------------------------------------
# Topology policy
# ---------------------------------------------------------------------------


class TopologyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifold_required: bool = False
    quad_ratio_min: float = Field(default=0.0, ge=0.0, le=1.0)
    max_face_count: Optional[int] = Field(default=None, ge=1)
    max_vertex_count: Optional[int] = Field(default=None, ge=1)


# ---------------------------------------------------------------------------
# Soft constraints
# ---------------------------------------------------------------------------


class SoftConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    metric: SoftMetric
    direction: SoftDirection
    target: float
    tolerance: float = Field(default=0.0, ge=0.0)
    weight: float = Field(default=1.0, gt=0.0)


# ---------------------------------------------------------------------------
# Style intent + judge
# ---------------------------------------------------------------------------


class StyleIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explicit: bool = False
    style: Optional[str] = None
    concept: Optional[str] = None
    concept_aliases: List[str] = Field(default_factory=list)
    acceptable_styles: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_explicit_requires_style(self) -> "StyleIntent":
        if self.explicit and not self.style:
            raise ValueError("explicit=true requires 'style' to be set")
        return self


class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected_style: str
    detected_concept: str
    style_alignment_pass: bool
    concept_alignment_pass: bool
    semantic: float = Field(ge=1.0, le=5.0)
    aesthetic: float = Field(ge=1.0, le=5.0)
    professional: float = Field(ge=1.0, le=5.0)
    stddev: float = Field(ge=0.0)
    judged_under_standard: str
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    raw_responses: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Artifact policy
# ---------------------------------------------------------------------------


class ArtifactPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_screenshot: bool = True
    write_scene_stats: bool = True


# ---------------------------------------------------------------------------
# Scene snapshot (returned from Blender worker)
# ---------------------------------------------------------------------------


class MaterialSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    base_color: List[float] = Field(default_factory=lambda: [0.8, 0.8, 0.8, 1.0])


class SceneMeshSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    object_type: str = "MESH"
    vertex_count: int = 0
    edge_count: int = 0
    face_count: int = 0
    face_sizes: Dict[str, int] = Field(default_factory=dict)
    manifold: bool = False
    bbox_min: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    bbox_max: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    location: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: List[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0])
    materials: List[MaterialSnapshot] = Field(default_factory=list)


class SceneSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_object: Optional[str] = None
    total_objects: int = 0
    total_mesh_objects: int = 0
    total_vertices: int = 0
    total_faces: int = 0
    quad_ratio: float = 0.0
    manifold: bool = False
    bbox_min: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    bbox_max: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    mesh_objects: List[SceneMeshSnapshot] = Field(default_factory=list)

    @property
    def bbox_size(self) -> List[float]:
        return [
            self.bbox_max[0] - self.bbox_min[0],
            self.bbox_max[1] - self.bbox_min[1],
            self.bbox_max[2] - self.bbox_min[2],
        ]


# ---------------------------------------------------------------------------
# v3.0 TestCaseCard
# ---------------------------------------------------------------------------


class TestCaseCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_version: str = FIXTURE_VERSION
    id: str
    category: Category
    difficulty: Difficulty
    task_family: TaskFamily
    prompt_variants: List[str] = Field(..., min_length=1)
    initial_scene: InitialScene = Field(default_factory=InitialScene)
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    topology_policy: TopologyPolicy = Field(default_factory=TopologyPolicy)
    soft_constraints: List[SoftConstraint] = Field(default_factory=list)
    style_intent: StyleIntent = Field(default_factory=StyleIntent)
    judge_policy: JudgePolicy = JudgePolicy.SCORE
    artifact_policy: ArtifactPolicy = Field(default_factory=ArtifactPolicy)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt_variants")
    @classmethod
    def _trim_prompts(cls, value: List[str]) -> List[str]:
        cleaned = [v.strip() for v in value if str(v).strip()]
        if not cleaned:
            raise ValueError("prompt_variants must include at least one non-empty variant")
        return cleaned


# ---------------------------------------------------------------------------
# Model invocation + evaluation result
# ---------------------------------------------------------------------------


class ModelInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    prompt_template_version: str = PROMPT_TEMPLATE_VERSION
    prompt: str
    raw_output: Any = None
    detected_contract: OutputContract = OutputContract.AUTO
    normalized_output: List[NormalizedStep] = Field(default_factory=list)
    parse_success: bool = False
    safety_success: bool = False
    model_latency_ms: float = 0.0
    cost_usd: float = 0.0
    parse_error: Optional[str] = None


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hard_pass: bool = False
    topology_pass: bool = False
    soft_score: float = Field(default=0.0, ge=0.0, le=1.0)
    hard_violations: List[str] = Field(default_factory=list)
    topology_violations: List[str] = Field(default_factory=list)
    failure_class: FailureClass = FailureClass.NONE
    failure_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Attempt artifact
# ---------------------------------------------------------------------------


class AttemptArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    attempt_index: int
    model_id: str
    prompt_used: str
    raw_output: Any = None
    normalized_output: List[NormalizedStep] = Field(default_factory=list)
    parse_success: bool = False
    safety_success: bool = False
    execution_success: bool = False
    passed_hard_constraints: bool = False
    passed_topology: bool = False
    soft_score: float = Field(default=0.0, ge=0.0, le=1.0)
    pass_overall: bool = False
    failure_class: FailureClass = FailureClass.NONE
    failure_reason: Optional[str] = None
    scene_snapshot: SceneSnapshot = Field(default_factory=SceneSnapshot)
    judge_result: Optional[JudgeResult] = None
    screenshot_path: str = ""
    scene_stats_path: str = ""
    model_latency_ms: float = 0.0
    execution_latency_ms: float = 0.0
    cost_usd: float = 0.0
    is_honeypot: bool = False


# ---------------------------------------------------------------------------
# Run-level models
# ---------------------------------------------------------------------------


class BenchmarkRunConfig(BaseModel):
    """Snapshot of CLI arguments for this run (audit trail)."""
    model_config = ConfigDict(extra="allow")

    cases: int = 0
    pass_at_k: int = 3
    models: List[str] = Field(default_factory=list)
    judge_model: str = ""
    system_prompt_version: str = "eval-default"
    temperature: float = 0.7
    seed: int = 42
    workers: int = 1
    simple_mode: bool = False
    suite_path: str = ""
    output_dir: str = ""
    judge_budget: float = 10.0
    difficulty_dist: Dict[str, float] = Field(default_factory=dict)
    mock_blender: bool = False


class RunMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_cases: int = 0
    total_attempts: int = 0
    execution_success_rate: float = 0.0
    hard_pass_rate: float = 0.0
    topology_pass_rate: float = 0.0
    avg_soft_score: float = 0.0
    pass_at_1: float = 0.0
    pass_at_3: float = 0.0
    avg_judge_semantic: Optional[float] = None
    avg_judge_aesthetic: Optional[float] = None
    avg_judge_professional: Optional[float] = None
    judge_reliable: bool = True
    judge_honeypot_catch_rate: Optional[float] = None
    avg_model_latency_ms: float = 0.0
    avg_execution_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    total_duration_s: float = 0.0
    difficulty_dist: Dict[str, int] = Field(default_factory=dict)
    category_dist: Dict[str, int] = Field(default_factory=dict)
    top_failure_reasons: Dict[str, int] = Field(default_factory=dict)


class BenchmarkRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    run_group_id: str
    timestamp_utc: str
    model_id: str
    suite_id: str
    fixture_version: str = FIXTURE_VERSION
    prompt_template_version: str = PROMPT_TEMPLATE_VERSION
    config: BenchmarkRunConfig
    attempts: List[AttemptArtifact] = Field(default_factory=list)
    metrics: RunMetrics = Field(default_factory=RunMetrics)
    report_md_path: str = ""
    report_json_path: str = ""
    git_commit: str = ""
    notes: str = ""


# ---------------------------------------------------------------------------
# TestSuite
# ---------------------------------------------------------------------------


class TestSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_id: str = "nalana-benchmark-v3"
    fixture_version: str = FIXTURE_VERSION
    cases: List[TestCaseCard]

    @classmethod
    def from_json(cls, filepath: str) -> "TestSuite":
        data = json.loads(Path(filepath).read_text(encoding="utf-8"))
        if isinstance(data, list):
            payload: Dict[str, Any] = {
                "suite_id": Path(filepath).stem,
                "fixture_version": FIXTURE_VERSION,
                "cases": data,
            }
        elif isinstance(data, dict) and "cases" in data:
            payload = data
        else:
            raise ValueError(f"Unsupported suite format in {filepath}: {type(data).__name__}")
        return cls.model_validate(payload)

    @classmethod
    def from_json_or_dir(cls, path: str) -> "TestSuite":
        p = Path(path)
        if p.is_dir():
            all_cases: List[Dict[str, Any]] = []
            for json_file in sorted(p.glob("*.json")):
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    all_cases.extend(data)
                elif isinstance(data, dict) and "cases" in data:
                    all_cases.extend(data["cases"])
            return cls.model_validate(
                {"suite_id": p.name, "fixture_version": FIXTURE_VERSION, "cases": all_cases}
            )
        return cls.from_json(str(p))

    def to_jsonable(self) -> Dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)
