"""Google Gemini model runner."""
from __future__ import annotations

import os
from typing import Dict, Optional

from nalana_eval.runners.base import BaseModelRunner

_PRICING: Dict[str, Dict[str, float]] = {
    "gemini-2.5-pro": {"input": 0.00125, "output": 0.01},
    "gemini-2.0-flash": {"input": 0.000075, "output": 0.0003},
}


class GeminiRunner(BaseModelRunner):
    def __init__(
        self,
        model_id: str = "gemini-2.5-pro",
        api_key: Optional[str] = None,
        **kwargs: object,
    ) -> None:
        resolved_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        super().__init__(model_id=model_id, api_key=resolved_key, **kwargs)  # type: ignore[arg-type]
        self._last_input_tokens = 0
        self._last_output_tokens = 0

    def _generate(self, prompt: str, temperature: float, seed: int) -> str:
        from google import genai  # noqa: PLC0415
        from google.genai import types  # noqa: PLC0415

        client = genai.Client(api_key=self.api_key)
        contents = []
        if self.system_prompt:
            contents.append(self.system_prompt + "\n\n" + prompt)
        else:
            contents.append(prompt)

        resp = client.models.generate_content(
            model=self.model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
                max_output_tokens=self.max_tokens,
            ),
        )
        if hasattr(resp, "usage_metadata") and resp.usage_metadata:
            self._last_input_tokens = resp.usage_metadata.prompt_token_count or 0
            self._last_output_tokens = resp.usage_metadata.candidates_token_count or 0
        return resp.text or ""

    def _estimate_cost(self, raw_output: str, prompt: str) -> float:
        prices = _PRICING.get(self.model_id, {"input": 0.0, "output": 0.0})
        return (
            self._last_input_tokens * prices["input"] / 1000.0
            + self._last_output_tokens * prices["output"] / 1000.0
        )
