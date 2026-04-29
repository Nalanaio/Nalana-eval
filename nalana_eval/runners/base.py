"""Abstract base class for LLM model runners."""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from nalana_eval.contracts import normalize_model_output
from nalana_eval.schema import (
    AttemptArtifact,
    FailureClass,
    ModelInvocation,
    OutputContract,
    TestCaseCard,
)

logger = logging.getLogger(__name__)


def _build_retry_context(previous_attempts: List[AttemptArtifact]) -> str:
    lines = [
        "\n\n---\nPrevious attempt(s) failed. Use this context to improve your response:",
        "IMPORTANT: The scene is fully reset to its initial state before each attempt.",
        "Your response must include ALL operations needed to complete the task from scratch — do not assume anything from previous attempts carries over.",
    ]
    for prev in previous_attempts:
        lines.append(f"\nAttempt {prev.attempt_index + 1}:")
        lines.append(f"  Failure: {prev.failure_class.value} — {prev.failure_reason or 'unknown reason'}")

        if prev.normalized_output:
            step_strs = [
                f"{s.kind.value}({', '.join(f'{k}={v}' for k, v in s.args.items())})"
                for s in prev.normalized_output
            ]
            lines.append(f"  Commands executed: {', '.join(step_strs)}")
        elif prev.raw_output is not None:
            raw_str = (
                prev.raw_output if isinstance(prev.raw_output, str)
                else json.dumps(prev.raw_output)
            )
            lines.append(f"  Your output (truncated): {raw_str[:400]}")

        snap = prev.scene_snapshot
        if snap.mesh_objects:
            obj_strs = [
                f"{m.name}(verts={m.vertex_count}, faces={m.face_count}, "
                f"location=[{', '.join(f'{x:.2f}' for x in m.location)}])"
                for m in snap.mesh_objects
            ]
            lines.append(
                f"  Scene after execution: {snap.total_mesh_objects} mesh object(s) — "
                + ", ".join(obj_strs)
            )
        elif prev.execution_success:
            lines.append("  Scene after execution: 0 mesh objects")

    lines.append("\nPlease fix the issues described above.\n---")
    return "\n".join(lines)


class BaseModelRunner(ABC):
    """Subclasses implement `_generate` and optionally `_estimate_cost`."""

    def __init__(
        self,
        model_id: str,
        system_prompt: str = "",
        api_key: str = "",
        temperature: float = 0.7,
        seed: int = 42,
        max_tokens: int = 2048,
    ) -> None:
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.api_key = api_key
        self.temperature = temperature
        self.seed = seed
        self.max_tokens = max_tokens

    @abstractmethod
    def _generate(self, prompt: str, temperature: float, seed: int) -> str:
        """Return raw LLM output string. Raise on API error."""

    def _estimate_cost(self, raw_output: str, prompt: str) -> float:
        return 0.0

    def generate(
        self,
        prompt: str,
        case: TestCaseCard,
        attempt_index: int,
        previous_attempts: Optional[List[AttemptArtifact]] = None,
    ) -> ModelInvocation:
        """Call the model and normalize output. Never raises — failures recorded in result."""
        invocation = ModelInvocation(
            model_id=self.model_id,
            prompt=prompt,
        )

        effective_prompt = prompt
        if previous_attempts:
            effective_prompt = prompt + _build_retry_context(previous_attempts)

        started = time.perf_counter()
        try:
            raw_str = self._generate(effective_prompt, self.temperature, self.seed + attempt_index)
        except Exception as exc:
            invocation.model_latency_ms = (time.perf_counter() - started) * 1000.0
            invocation.parse_error = f"API error: {exc}"
            logger.warning("Model %s API call failed (case=%s): %s", self.model_id, case.id, exc)
            return invocation

        invocation.model_latency_ms = (time.perf_counter() - started) * 1000.0
        invocation.raw_output = raw_str
        invocation.cost_usd = self._estimate_cost(raw_str, prompt)

        # Try to parse JSON first (parse_success)
        try:
            parsed_json = json.loads(raw_str) if isinstance(raw_str, str) else raw_str
        except json.JSONDecodeError as exc:
            invocation.parse_error = f"JSON parse error: {exc}"
            logger.debug("Parse error for %s attempt %d: %s", case.id, attempt_index, exc)
            return invocation

        # Normalize + safety check (both happen inside normalize_model_output)
        try:
            steps, contract = normalize_model_output(raw_str)
            invocation.normalized_output = steps
            invocation.detected_contract = contract
            invocation.parse_success = True
            invocation.safety_success = True
        except ValueError as exc:
            err = str(exc)
            invocation.parse_error = err
            # Distinguish safety block from parse error by message content
            if "Blocked operation" in err or "not allowed" in err.lower():
                invocation.parse_success = True
                invocation.safety_success = False
                logger.warning(
                    "Safety blocked for %s attempt %d: %s", case.id, attempt_index, err
                )
            else:
                logger.debug("Normalize error for %s attempt %d: %s", case.id, attempt_index, err)

        return invocation
