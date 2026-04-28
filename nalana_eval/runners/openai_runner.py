"""OpenAI model runner.

Works with either a standard OpenAI API key or Azure AI Foundry:
  Standard:  set OPENAI_API_KEY               → uses openai.OpenAI
  Azure:     set AZURE_OPENAI_API_KEY
             + AZURE_OPENAI_ENDPOINT           → uses openai.AzureOpenAI
             + AZURE_OPENAI_API_VERSION
             + GPT55_DEPLOYMENT_NAME (optional, defaults to model_id)
  Azure vars take precedence when both are present.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from nalana_eval.runners.base import BaseModelRunner

_PRICING: Dict[str, Dict[str, float]] = {
    "gpt-5.5":     {"input": 0.0, "output": 0.0},
    "gpt-5.4":     {"input": 0.0, "output": 0.0},
    "gpt-4o":      {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
}

_DEFAULT_API_VERSION = "2025-01-01-preview"

# gpt-5.x and o-series have restricted parameters compared to gpt-4o.
# They reject: max_tokens, temperature != 1, seed.
_RESTRICTED_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _is_restricted(model_id: str) -> bool:
    return any(model_id.startswith(p) for p in _RESTRICTED_PREFIXES)


def _build_params(model_id: str, temperature: float, seed: int, max_tokens: int) -> Dict[str, Any]:
    """Return the right set of parameters for the given model family."""
    if _is_restricted(model_id):
        # These models only accept temperature=1 and don't support seed or max_tokens.
        return {"max_completion_tokens": max_tokens}
    return {
        "temperature": temperature,
        "seed": seed,
        "max_tokens": max_tokens,
    }


class OpenAIRunner(BaseModelRunner):
    def __init__(
        self,
        model_id: str = "gpt-4o",
        api_key: Optional[str] = None,
        **kwargs: object,
    ) -> None:
        self._azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        self._api_version    = os.environ.get("AZURE_OPENAI_API_VERSION", _DEFAULT_API_VERSION)
        self._deployment     = os.environ.get("GPT55_DEPLOYMENT_NAME", model_id)

        if self._azure_endpoint:
            resolved_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY", "")
        else:
            resolved_key = api_key or os.environ.get("OPENAI_API_KEY", "")

        super().__init__(model_id=model_id, api_key=resolved_key, **kwargs)  # type: ignore[arg-type]
        self._last_input_tokens  = 0
        self._last_output_tokens = 0

    def _generate(self, prompt: str, temperature: float, seed: int) -> str:
        if self._azure_endpoint:
            from openai import AzureOpenAI  # noqa: PLC0415
            client = AzureOpenAI(
                azure_endpoint=self._azure_endpoint,
                api_key=self.api_key,
                api_version=self._api_version,
            )
            deployment = self._deployment
        else:
            from openai import OpenAI  # noqa: PLC0415
            client = OpenAI(api_key=self.api_key)
            deployment = self.model_id

        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = client.chat.completions.create(
            model=deployment,
            messages=messages,
            response_format={"type": "json_object"},
            **_build_params(deployment, temperature, seed, self.max_tokens),
        )
        if resp.usage:
            self._last_input_tokens  = resp.usage.prompt_tokens
            self._last_output_tokens = resp.usage.completion_tokens
        return resp.choices[0].message.content or ""

    def _estimate_cost(self, raw_output: str, prompt: str) -> float:
        prices = _PRICING.get(self.model_id, {"input": 0.0, "output": 0.0})
        return (
            self._last_input_tokens  * prices["input"]  / 1000.0
            + self._last_output_tokens * prices["output"] / 1000.0
        )
