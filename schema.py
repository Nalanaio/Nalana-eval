import json
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FIXTURE_VERSION = "2.0"
PROMPT_TEMPLATE_VERSION = "benchmark-execution-v1"


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


class OutputContract(str, Enum):
    AUTO = "auto"
    NORMALIZED = "normalized"
    LEGACY_OPS = "legacy_ops"
    TYPED_COMMANDS = "typed_commands"


class ReferenceMode(str, Enum):
    DYNAMIC = "dynamic"
    TARGET_ASSET = "target_asset"


class FailureClass(str, Enum):
    NONE = "NONE"
    PARSE_ERROR = "PARSE_ERROR"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    COVERAGE_GAP = "COVERAGE_GAP"
    GEOMETRY_MISMATCH = "GEOMETRY_MISMATCH"
    MODEL_ERROR = "MODEL_ERROR"
    RPC_ERROR = "RPC_ERROR"
    REFERENCE_ERROR = "REFERENCE_ERROR"


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
    screenshot: Optional[str] = None
    objects: List[SceneSeed] = Field(default_factory=list)

    @field_validator("mode")
    @classmethod
    def _normalize_mode(cls, value: str) -> str:
        return str(value or "OBJECT").upper()


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
        payload = {
            "kind": self.kind.value,
            "args": self.args,
        }
        return payload

    def signature_hash(self) -> str:
        serialized = json.dumps(self.signature(), sort_keys=True, separators=(",", ":"))
        return sha256(serialized.encode("utf-8")).hexdigest()


class QualitySignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quad_ratio_min: float = Field(default=0.85, ge=0.0, le=1.0)
    manifold: bool = True
    chamfer_threshold: float = Field(default=0.001, ge=0.0)


class ReferencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ReferenceMode = ReferenceMode.DYNAMIC
    repeat_runs: int = Field(default=2, ge=1, le=5)
    require_typed_coverage: bool = False


class CompiledPayloads(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legacy_ops: List[LegacyOperation] = Field(default_factory=list)
    typed_commands: List[TypedCommandPayload] = Field(default_factory=list)


class TestCaseCard(BaseModel):
    model_config = ConfigDict(extra="allow")

    fixture_version: str = FIXTURE_VERSION
    id: str
    category: Category
    difficulty: Difficulty
    voice_commands: List[str] = Field(..., min_length=1)
    initial_scene: InitialScene = Field(default_factory=InitialScene)
    expected_steps: List[NormalizedStep] = Field(default_factory=list)
    reference_policy: ReferencePolicy = Field(default_factory=ReferencePolicy)
    quality_signals: QualitySignals = Field(default_factory=QualitySignals)
    target_mesh: Optional[str] = None
    ground_truth: Optional[List[LegacyOperation]] = None
    compiled_payloads: Optional[CompiledPayloads] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("voice_commands")
    @classmethod
    def _trim_voice_commands(cls, value: List[str]) -> List[str]:
        cleaned = [command.strip() for command in value if str(command).strip()]
        if not cleaned:
            raise ValueError("Each case must include at least one non-empty voice command")
        return cleaned

    @model_validator(mode="after")
    def _hydrate_compatibility(self) -> "TestCaseCard":
        try:
            from .contracts import (
                compile_step_to_legacy_op,
                compile_step_to_typed_command,
                normalize_legacy_operation,
            )
        except ImportError:  # pragma: no cover - Blender script fallback
            from contracts import compile_step_to_legacy_op, compile_step_to_typed_command, normalize_legacy_operation

        if self.ground_truth and not self.expected_steps:
            self.expected_steps = [normalize_legacy_operation(op.model_dump()) for op in self.ground_truth]

        if not self.fixture_version:
            self.fixture_version = FIXTURE_VERSION

        if self.compiled_payloads is None:
            legacy_ops: List[LegacyOperation] = []
            typed_commands: List[TypedCommandPayload] = []
            for step in self.expected_steps:
                try:
                    legacy_ops.append(compile_step_to_legacy_op(step))
                except ValueError:
                    pass
                typed = compile_step_to_typed_command(step)
                if typed is not None:
                    typed_commands.append(typed)
            self.compiled_payloads = CompiledPayloads(
                legacy_ops=legacy_ops,
                typed_commands=typed_commands,
            )

        return self

    @property
    def has_full_typed_coverage(self) -> bool:
        return bool(self.expected_steps) and len(self.compiled_payloads.typed_commands) == len(self.expected_steps)


class SceneMeshSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    object_type: str
    vertex_count: int = 0
    edge_count: int = 0
    face_count: int = 0
    face_sizes: Dict[str, int] = Field(default_factory=dict)
    # topology checks (computed by executor, aggregated into TopologyScore)
    manifold: bool = False
    loose_geometry_count: int = 0
    face_quality_score: float = 1.0
    flipped_face_count: int = 0
    overlapping_verts: int = 0
    duplicate_faces: int = 0
    world_vertices: List[List[float]] = Field(default_factory=list)
    world_faces: List[List[int]] = Field(default_factory=list)
    location: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: List[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0])


class SceneSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_object: Optional[str] = None
    total_objects: int = 0
    total_mesh_objects: int = 0
    total_vertices: int = 0
    total_faces: int = 0
    geometry_signature: str = ""
    mesh_objects: List[SceneMeshSnapshot] = Field(default_factory=list)


class TopologyScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 1. Manifold — mesh is closed with no open edges or holes
    manifold: bool = False
    # 2. Loose geometry — stray verts/edges not attached to any face
    loose_geometry_count: int = 0
    # 3. Face quality
    quad_ratio: float = 0.0          # quads / total faces (used by quality_signals.quad_ratio_min)
    face_quality_score: float = 0.0  # (tris + quads with nonzero area) / total faces
    # 4. Normal direction — faces whose normal points inward
    flipped_face_count: int = 0
    # 5. Self-overlap / duplicates
    overlapping_verts: int = 0
    duplicate_faces: int = 0


class ModelInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    prompt_template_version: str = PROMPT_TEMPLATE_VERSION
    prompt: str
    raw_output: Any = None
    detected_contract: OutputContract = OutputContract.AUTO
    normalized_output: List[NormalizedStep] = Field(default_factory=list)
    model_latency_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    parse_error: Optional[str] = None


class AttemptArtifact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    case_id: str
    attempt_index: int
    voice_command: str
    prompt: str
    model_id: str
    detected_contract: OutputContract = OutputContract.AUTO
    raw_output: Any = None
    normalized_output: List[NormalizedStep] = Field(default_factory=list)
    compiled_legacy_ops: List[LegacyOperation] = Field(default_factory=list)
    compiled_typed_commands: List[TypedCommandPayload] = Field(default_factory=list)
    parse_success: bool = False
    safety_success: bool = False
    execution_success: bool = False
    geometry_success: bool = False
    passed: bool = False
    failure_class: FailureClass = FailureClass.NONE
    error_message: Optional[str] = None
    coverage_gaps: List[str] = Field(default_factory=list)
    model_latency_ms: float = 0.0
    execution_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    command_accuracy: float = 0.0
    parameter_accuracy: float = 0.0
    sequence_accuracy: float = 0.0
    topology_score: Optional["TopologyScore"] = None
    chamfer_distance: Optional[float] = None
    sampling_mode: Optional[str] = None
    reference_signature: Optional[str] = None
    candidate_signature: Optional[str] = None
    render_path: Optional[str] = None


class CaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: Category
    difficulty: Difficulty
    reference_signature: Optional[str] = None
    typed_coverage: bool = False
    attempts: List[AttemptArtifact] = Field(default_factory=list)
    pass_at_1: float = 0.0
    pass_at_k: float = 0.0
    best_attempt_index: Optional[int] = None
    failure_summary: Dict[str, int] = Field(default_factory=dict)


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_cases: int = 0
    total_attempts: int = 0
    execution_success_rate: float = 0.0
    geometry_success_rate: float = 0.0
    pass_at_1: float = 0.0
    pass_at_k: float = 0.0
    avg_command_accuracy: float = 0.0
    avg_parameter_accuracy: float = 0.0
    avg_sequence_accuracy: float = 0.0
    avg_latency_ms: float = 0.0
    avg_chamfer_distance: Optional[float] = None
    category_breakdown: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    difficulty_breakdown: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    top_failure_reasons: Dict[str, int] = Field(default_factory=dict)


class BenchmarkRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_id: str
    fixture_version: str
    prompt_template_version: str
    model_id: str
    generated_at: str
    baseline_reference: Optional[str] = None
    baseline_created: bool = False
    baseline_deltas: Dict[str, Optional[float]] = Field(default_factory=dict)
    case_results: List[CaseResult] = Field(default_factory=list)
    summary: RunSummary = Field(default_factory=RunSummary)
    report_markdown_path: Optional[str] = None
    report_json_path: Optional[str] = None


class TestSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_id: str = "nalana-benchmark"
    fixture_version: str = FIXTURE_VERSION
    prompt_template_version: str = PROMPT_TEMPLATE_VERSION
    cases: List[TestCaseCard]

    @classmethod
    def from_json(cls, filepath: str) -> "TestSuite":
        with open(filepath, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        if isinstance(data, list):
            payload = {
                "suite_id": Path(filepath).stem,
                "fixture_version": FIXTURE_VERSION,
                "prompt_template_version": PROMPT_TEMPLATE_VERSION,
                "cases": data,
            }
        elif isinstance(data, dict):
            if "cases" in data:
                payload = data
            else:
                payload = {
                    "suite_id": Path(filepath).stem,
                    "fixture_version": FIXTURE_VERSION,
                    "prompt_template_version": PROMPT_TEMPLATE_VERSION,
                    "cases": data.get("items", []),
                }
        else:
            raise ValueError(f"Unsupported suite payload in {filepath}: {type(data).__name__}")

        suite = cls.model_validate(payload)
        if not suite.fixture_version:
            suite.fixture_version = FIXTURE_VERSION
        if not suite.prompt_template_version:
            suite.prompt_template_version = PROMPT_TEMPLATE_VERSION
        return suite

    def to_jsonable(self) -> Dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)
