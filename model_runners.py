import time
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

