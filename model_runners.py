import json
import os
import time
import urllib.error
import urllib.request
import xmlrpc.client
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

try:
    from .contracts import normalize_model_output
    from .schema import ModelInvocation, OutputContract, PROMPT_TEMPLATE_VERSION, TestCaseCard
except ImportError:  # pragma: no cover - Blender script fallback
    from contracts import normalize_model_output
    from schema import ModelInvocation, OutputContract, PROMPT_TEMPLATE_VERSION, TestCaseCard


class ModelRunner(ABC):
    def __init__(
        self,
        *,
        model_id: str,
        output_contract: OutputContract = OutputContract.LEGACY_OPS,
        prompt_template_version: str = PROMPT_TEMPLATE_VERSION,
    ):
        self.model_id = model_id
        self.output_contract = output_contract
        self.prompt_template_version = prompt_template_version

    def build_prompt(self, case: TestCaseCard, voice_command: str) -> str:
        contract_guidance = {
            OutputContract.LEGACY_OPS: (
                "Return only a JSON array of legacy Blender operations shaped as "
                '{"op":"bpy.ops.<module>.<operator>","params":{...}}.'
            ),
            OutputContract.TYPED_COMMANDS: (
                "Return only a JSON array of typed Nalana commands shaped as "
                '{"type":"COMMAND_NAME","args":{...}}.'
            ),
            OutputContract.NORMALIZED: (
                "Return only a JSON array of canonical benchmark steps shaped as "
                '{"kind":"STEP_KIND","args":{...}}.'
            ),
            OutputContract.AUTO: "Return only JSON commands with no prose or code fences.",
        }[self.output_contract]

        scene_bits = [f"Initial mode: {case.initial_scene.mode}."]
        if case.initial_scene.active_object:
            scene_bits.append(f"Active object: {case.initial_scene.active_object}.")
        if case.initial_scene.objects:
            seeded = ", ".join(seed.primitive for seed in case.initial_scene.objects)
            scene_bits.append(f"Seeded objects: {seeded}.")

        return "\n".join(
            [
                "You are generating Nalana execution-stage output for a benchmark case.",
                contract_guidance,
                f"Voice command: {voice_command}",
                f"Category: {case.category.value}. Difficulty: {case.difficulty.value}.",
                " ".join(scene_bits),
                "Do not include explanations.",
            ]
        )

    def invoke(self, case: TestCaseCard, voice_command: str, attempt_index: int) -> ModelInvocation:
        prompt = self.build_prompt(case, voice_command)
        started = time.perf_counter()
        try:
            raw_output = self._generate(case, voice_command, attempt_index, prompt)
        except Exception as exc:
            return ModelInvocation(
                model_id=self.model_id,
                prompt_template_version=self.prompt_template_version,
                prompt=prompt,
                raw_output=None,
                detected_contract=self.output_contract,
                normalized_output=[],
                model_latency_ms=(time.perf_counter() - started) * 1000.0,
                parse_error=str(exc),
                metadata={"runner_error": True},
            )

        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            normalized_output, detected_contract = normalize_model_output(raw_output)
            parse_error = None
        except Exception as exc:
            normalized_output = []
            detected_contract = self.output_contract
            parse_error = str(exc)

        return ModelInvocation(
            model_id=self.model_id,
            prompt_template_version=self.prompt_template_version,
            prompt=prompt,
            raw_output=raw_output,
            detected_contract=detected_contract,
            normalized_output=normalized_output,
            model_latency_ms=latency_ms,
            parse_error=parse_error,
            metadata={"attempt_index": attempt_index},
        )

    @abstractmethod
    def _generate(self, case: TestCaseCard, voice_command: str, attempt_index: int, prompt: str) -> Any:
        raise NotImplementedError


class StaticPayloadRunner(ModelRunner):
    def __init__(
        self,
        payloads: Dict[Any, Any],
        *,
        model_id: str = "static-runner",
        output_contract: OutputContract = OutputContract.LEGACY_OPS,
        prompt_template_version: str = PROMPT_TEMPLATE_VERSION,
    ):
        super().__init__(
            model_id=model_id,
            output_contract=output_contract,
            prompt_template_version=prompt_template_version,
        )
        self.payloads = payloads

    def _generate(self, case: TestCaseCard, voice_command: str, attempt_index: int, prompt: str) -> Any:
        candidates = [
            (case.id, attempt_index),
            case.id,
            voice_command,
        ]
        for key in candidates:
            if key in self.payloads:
                return self.payloads[key]
        raise KeyError(f"No static payload configured for case {case.id} attempt {attempt_index}")


class CallableModelRunner(ModelRunner):
    def __init__(
        self,
        generator: Callable[[TestCaseCard, str, int, str], Any],
        *,
        model_id: str,
        output_contract: OutputContract = OutputContract.LEGACY_OPS,
        prompt_template_version: str = PROMPT_TEMPLATE_VERSION,
    ):
        super().__init__(
            model_id=model_id,
            output_contract=output_contract,
            prompt_template_version=prompt_template_version,
        )
        self.generator = generator

    def _generate(self, case: TestCaseCard, voice_command: str, attempt_index: int, prompt: str) -> Any:
        return self.generator(case, voice_command, attempt_index, prompt)


class XmlRpcModelRunner(ModelRunner):
    def __init__(
        self,
        rpc_url: str,
        *,
        method_name: str = "generate_json_payload",
        payload_style: str = "prompt_only",
        model_id: str = "xmlrpc-model",
        output_contract: OutputContract = OutputContract.LEGACY_OPS,
        prompt_template_version: str = PROMPT_TEMPLATE_VERSION,
    ):
        super().__init__(
            model_id=model_id,
            output_contract=output_contract,
            prompt_template_version=prompt_template_version,
        )
        self.rpc = xmlrpc.client.ServerProxy(rpc_url, allow_none=True)
        self.method_name = method_name
        self.payload_style = payload_style

    def _generate(self, case: TestCaseCard, voice_command: str, attempt_index: int, prompt: str) -> Any:
        method = getattr(self.rpc, self.method_name)
        if self.payload_style == "structured":
            return method(
                {
                    "prompt": prompt,
                    "voice_command": voice_command,
                    "attempt_index": attempt_index,
                    "case_id": case.id,
                    "expected_contract": self.output_contract.value,
                }
            )
        return method(prompt)


class GeminiRunner(StaticPayloadRunner):
    def __init__(
        self,
        payloads: Dict[Any, Any],
        *,
        output_contract: OutputContract = OutputContract.LEGACY_OPS,
        prompt_template_version: str = PROMPT_TEMPLATE_VERSION,
    ):
        super().__init__(
            payloads,
            model_id="google-gemini-3-pro",
            output_contract=output_contract,
            prompt_template_version=prompt_template_version,
        )


def _post(url: str, body: Any, headers: Optional[Dict[str, str]] = None, *, timeout: int = 60) -> Any:
    payload = json.dumps(body).encode()
    all_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=payload, headers=all_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc


def _unwrap_fences(text: str) -> str:
    """Strip ```...``` wrappers that models sometimes add around their JSON."""
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    closing = next((i for i in range(len(lines) - 1, 0, -1) if lines[i].strip() == "```"), None)
    return "\n".join(lines[1:closing]).strip() if closing else s


class _LiveApiRunner(ModelRunner):
    """Base for runners that call a live model API. Handles key loading."""

    _ENV_VAR: str = ""

    def __init__(
        self,
        *,
        model_id: str,
        api_key: Optional[str] = None,
        output_contract: OutputContract = OutputContract.NORMALIZED,
        prompt_template_version: str = PROMPT_TEMPLATE_VERSION,
    ):
        super().__init__(
            model_id=model_id,
            output_contract=output_contract,
            prompt_template_version=prompt_template_version,
        )
        key = api_key or os.environ.get(self._ENV_VAR, "")
        if not key:
            raise ValueError(f"{self._ENV_VAR} is not set")
        self._key = key


class AnthropicRunner(_LiveApiRunner):
    _ENV_VAR = "ANTHROPIC_API_KEY"

    def __init__(self, *, model_id: str, max_tokens: int = 2048, **kwargs):
        super().__init__(model_id=model_id, **kwargs)
        self._max_tokens = max_tokens

    def _generate(self, case: TestCaseCard, voice_command: str, attempt_index: int, prompt: str) -> Any:
        resp = _post(
            "https://api.anthropic.com/v1/messages",
            body={"model": self.model_id, "max_tokens": self._max_tokens, "messages": [{"role": "user", "content": prompt}]},
            headers={"x-api-key": self._key, "anthropic-version": "2023-06-01"},
        )
        return _unwrap_fences(resp["content"][0]["text"])


class GeminiApiRunner(_LiveApiRunner):
    _ENV_VAR = "GEMINI_API_KEY"

    def __init__(self, *, model_id: str = "gemini-2.5-pro", **kwargs):
        super().__init__(model_id=model_id, **kwargs)

    def _generate(self, case: TestCaseCard, voice_command: str, attempt_index: int, prompt: str) -> Any:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_id}:generateContent?key={self._key}"
        try:
            resp = _post(url, body={"contents": [{"parts": [{"text": prompt}]}]})
        except RuntimeError as exc:
            raise RuntimeError(str(exc).replace(self._key, "<redacted>")) from None
        return _unwrap_fences(resp["candidates"][0]["content"]["parts"][0]["text"])


class OpenAICompatibleRunner(_LiveApiRunner):
    _ENV_VAR = "OPENAI_API_KEY"

    def _generate(self, case: TestCaseCard, voice_command: str, attempt_index: int, prompt: str) -> Any:
        resp = _post(
            "https://api.openai.com/v1/chat/completions",
            body={"model": self.model_id, "messages": [{"role": "user", "content": prompt}]},
            headers={"Authorization": f"Bearer {self._key}"},
        )
        return _unwrap_fences(resp["choices"][0]["message"]["content"])

