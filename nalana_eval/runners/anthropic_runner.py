"""Anthropic (Claude) model runner."""
from __future__ import annotations

import os
from typing import Dict, Optional

from nalana_eval.runners.base import BaseModelRunner

_PRICING: Dict[str, Dict[str, float]] = {
    "claude-opus-4-7": {"input": 0.015, "output": 0.075},
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
    "claude-haiku-4-5-20251001": {"input": 0.00025, "output": 0.00125},
}


class AnthropicRunner(BaseModelRunner):
    def __init__(
        self,
        model_id: str = "claude-sonnet-4-6",
        api_key: Optional[str] = None,
        **kwargs: object,
    ) -> None:
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        super().__init__(model_id=model_id, api_key=resolved_key, **kwargs)  # type: ignore[arg-type]
        self._last_input_tokens = 0
        self._last_output_tokens = 0

    def _generate(self, prompt: str, temperature: float, seed: int) -> str:
        import anthropic  # noqa: PLC0415
        client = anthropic.Anthropic(api_key=self.api_key)

        system = self.system_prompt or ""
        system += "\n\nIMPORTANT: Output ONLY valid JSON, no prose."

        resp = client.messages.create(
            model=self.model_id,
            system=system.strip(),
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=self.max_tokens,
            # Anthropic does not support seed parameter
        )
        if resp.usage:
            self._last_input_tokens = resp.usage.input_tokens
            self._last_output_tokens = resp.usage.output_tokens
        return resp.content[0].text if resp.content else ""

    def _estimate_cost(self, raw_output: str, prompt: str) -> float:
        prices = _PRICING.get(self.model_id, {"input": 0.0, "output": 0.0})
        return (
            self._last_input_tokens * prices["input"] / 1000.0
            + self._last_output_tokens * prices["output"] / 1000.0
        )
