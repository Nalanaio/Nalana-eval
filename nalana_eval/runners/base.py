"""Abstract base class for LLM model runners."""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from nalana_eval.contracts import normalize_model_output
from nalana_eval.schema import (
    FailureClass,
    ModelInvocation,
    OutputContract,
    TestCaseCard,
)

logger = logging.getLogger(__name__)


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
    ) -> ModelInvocation:
        """Call the model and normalize output. Never raises — failures recorded in result."""
        invocation = ModelInvocation(
            model_id=self.model_id,
            prompt=prompt,
        )

        started = time.perf_counter()
        try:
            raw_str = self._generate(prompt, self.temperature, self.seed + attempt_index)
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
