"""OpenAI model runner."""
from __future__ import annotations

import os
from typing import Dict, Optional

from nalana_eval.runners.base import BaseModelRunner

# Pricing per 1K tokens (USD). Kept as a reference; actual billing may differ.
_PRICING: Dict[str, Dict[str, float]] = {
    "gpt-5": {"input": 0.0125, "output": 0.05},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
}


class OpenAIRunner(BaseModelRunner):
    def __init__(
        self,
        model_id: str = "gpt-4o",
        api_key: Optional[str] = None,
        **kwargs: object,
    ) -> None:
        resolved_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        super().__init__(model_id=model_id, api_key=resolved_key, **kwargs)  # type: ignore[arg-type]
        self._last_input_tokens = 0
        self._last_output_tokens = 0

    def _generate(self, prompt: str, temperature: float, seed: int) -> str:
        from openai import OpenAI  # noqa: PLC0415
        client = OpenAI(api_key=self.api_key)
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            temperature=temperature,
            seed=seed,
            response_format={"type": "json_object"},
            max_tokens=self.max_tokens,
        )
        if resp.usage:
            self._last_input_tokens = resp.usage.prompt_tokens
            self._last_output_tokens = resp.usage.completion_tokens
        return resp.choices[0].message.content or ""

    def _estimate_cost(self, raw_output: str, prompt: str) -> float:
        prices = _PRICING.get(self.model_id, {"input": 0.0, "output": 0.0})
        return (
            self._last_input_tokens * prices["input"] / 1000.0
            + self._last_output_tokens * prices["output"] / 1000.0
        )
