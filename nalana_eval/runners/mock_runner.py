"""Mock model runner for testing. Serves pre-recorded responses from a fixture file."""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Optional

from nalana_eval.runners.base import BaseModelRunner


class MockRunner(BaseModelRunner):
    """Serves responses from a JSON fixture file.

    The fixture file is a dict mapping keys to raw LLM output strings.
    Key resolution order:
      1. f"{case_id}:{attempt_index}" (set via set_context before generate)
      2. f"{case_id}"
      3. sha256 of prompt (first 16 hex chars)
      4. "__default__" fallback
    """

    def __init__(
        self,
        payload_file: Optional[str] = None,
        payloads: Optional[Dict[str, Any]] = None,
        model_id: str = "mock",
        **kwargs: object,
    ) -> None:
        super().__init__(model_id=model_id, **kwargs)  # type: ignore[arg-type]
        if payloads is not None:
            self._payloads = payloads
        elif payload_file is not None:
            self._payloads = json.loads(Path(payload_file).read_text(encoding="utf-8"))
        else:
            self._payloads = {}
        self._current_case_id: str = ""
        self._current_attempt: int = 0

    def set_context(self, case_id: str, attempt_index: int) -> None:
        self._current_case_id = case_id
        self._current_attempt = attempt_index

    def _generate(self, prompt: str, temperature: float, seed: int) -> str:
        keys_to_try = [
            f"{self._current_case_id}:{self._current_attempt}",
            self._current_case_id,
            sha256(prompt.encode("utf-8")).hexdigest()[:16],
            "__default__",
        ]
        for key in keys_to_try:
            if key in self._payloads:
                value = self._payloads[key]
                return json.dumps(value) if not isinstance(value, str) else value

        # Default: return a minimal valid ADD_MESH step
        return json.dumps([{"kind": "ADD_MESH", "args": {"primitive": "CUBE"}}])

    def _estimate_cost(self, raw_output: str, prompt: str) -> float:
        return 0.0
