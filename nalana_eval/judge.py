"""LLM-as-Judge — multimodal scorer for 3D scene rendering quality.

Runs N=3 times per case, takes the median score.
Caches results in db/judge_cache.sqlite (30-day TTL).
Never decides pass/fail — only produces soft signal scores.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
import sqlite3
from hashlib import sha256
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Tuple

from nalana_eval.schema import JudgeResult, JudgePolicy, StyleIntent, TestCaseCard

logger = logging.getLogger(__name__)

_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "judge_prompt.md"
_JUDGE_RUNS = 3
_JUDGE_TEMPERATURE = 0.3
_JUDGE_MAX_TOKENS = 512
_CACHE_TTL_DAYS = 30


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


def _load_prompt_parts() -> Tuple[str, str]:
    """Extract system message and user message template from judge_prompt.md."""
    text = _PROMPT_FILE.read_text(encoding="utf-8")
    # Find all fenced code blocks (```) that are not language-tagged
    code_blocks = re.findall(r"^```\s*\n(.*?)\n```", text, re.DOTALL | re.MULTILINE)
    if len(code_blocks) < 2:
        raise RuntimeError(
            f"Could not parse {_PROMPT_FILE}: expected at least 2 fenced code blocks"
        )
    return code_blocks[0].strip(), code_blocks[1].strip()


def _build_style_intent_block(si: StyleIntent) -> str:
    if si.explicit and si.style:
        return "\n".join([
            "- explicit: true",
            f"- specified_style: {si.style}",
            f"- concept: {si.concept or 'null'}",
            f"- concept_aliases: {json.dumps(si.concept_aliases)}",
            "",
            "Author specified the style. The model MUST match it; otherwise style_alignment_pass = false.",
        ])
    if si.acceptable_styles:
        return "\n".join([
            "- explicit: false",
            f"- concept: {si.concept or 'null'}",
            f"- concept_aliases: {json.dumps(si.concept_aliases)}",
            f"- acceptable_styles: {json.dumps(si.acceptable_styles)}",
            "",
            "Author left style open. Identify what style the model chose, then judge by that style's standards.",
            "Style is acceptable if it appears in acceptable_styles.",
        ])
    return "\n".join([
        "- explicit: false",
        f"- concept: {si.concept or 'null'}",
        "- (no style restrictions)",
        "",
        "Author placed no style or concept restrictions. Judge holistically:",
        "- If concept is null, skip concept_recognizability (set to null in output)",
        "- Use whichever style the model chose; geometric_quality always applies",
    ])


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------


def _cache_key(prompt_used: str, screenshot_path: str, judge_model: str) -> str:
    with open(screenshot_path, "rb") as f:
        img_bytes = f.read()
    payload = f"{judge_model}|{prompt_used}|{sha256(img_bytes).hexdigest()}"
    return sha256(payload.encode("utf-8")).hexdigest()


def _get_cache(db_path: Path, key: str) -> Optional[Dict[str, Any]]:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT result_json FROM judge_cache WHERE key = ? "
            "AND created_at > datetime('now', ?)",
            (key, f"-{_CACHE_TTL_DAYS} days"),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception as exc:
        logger.warning("Judge cache read error: %s", exc)
    return None


def _set_cache(db_path: Path, key: str, result: Dict[str, Any]) -> None:
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS judge_cache "
            "(key TEXT PRIMARY KEY, result_json TEXT, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO judge_cache (key, result_json) VALUES (?, ?)",
            (key, json.dumps(result)),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("Judge cache write error: %s", exc)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_raw_response(raw: str) -> Dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
        else:
            raise ValueError(f"Cannot parse judge JSON: {raw[:300]}")

    scores = data.get("scores_within_detected_style") or {}
    concept_rec = scores.get("concept_recognizability")
    style_exec = float(scores.get("style_execution") or 3.0)
    geom_qual = float(scores.get("geometric_quality") or 3.0)

    semantic = float(concept_rec) if concept_rec is not None else style_exec
    semantic = max(1.0, min(5.0, semantic))
    aesthetic = max(1.0, min(5.0, style_exec))
    professional = max(1.0, min(5.0, geom_qual))

    return {
        "detected_style": str(data.get("detected_style") or "geometric"),
        "detected_concept": str(data.get("detected_concept") or ""),
        "style_alignment_pass": bool(data.get("style_alignment_pass", False)),
        "concept_alignment_pass": bool(data.get("concept_alignment_pass", True)),
        "semantic": semantic,
        "aesthetic": aesthetic,
        "professional": professional,
        "judged_under_standard": str(data.get("judged_under_standard") or "geometric"),
        "reasoning": str(data.get("reasoning") or ""),
        "confidence": float(data.get("confidence") or 0.5),
        "raw": data,
    }


# ---------------------------------------------------------------------------
# Provider-specific API calls
# ---------------------------------------------------------------------------


def _call_openai(
    system_msg: str,
    user_msg: str,
    image_b64: str,
    model: str,
    api_key: str,
) -> str:
    from openai import OpenAI  # noqa: PLC0415
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_msg},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            },
        ],
        temperature=_JUDGE_TEMPERATURE,
        response_format={"type": "json_object"},
        max_tokens=_JUDGE_MAX_TOKENS,
    )
    return resp.choices[0].message.content or ""


def _call_anthropic(
    system_msg: str,
    user_msg: str,
    image_b64: str,
    model: str,
    api_key: str,
) -> str:
    import anthropic  # noqa: PLC0415
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        system=system_msg + "\n\nIMPORTANT: Output ONLY valid JSON, no prose.",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": user_msg},
                ],
            }
        ],
        temperature=_JUDGE_TEMPERATURE,
        max_tokens=_JUDGE_MAX_TOKENS,
    )
    return resp.content[0].text


def _call_gemini(
    system_msg: str,
    user_msg: str,
    image_bytes: bytes,
    model: str,
    api_key: str,
) -> str:
    from google import genai  # noqa: PLC0415
    from google.genai import types  # noqa: PLC0415
    client = genai.Client(api_key=api_key)
    full_text = system_msg + "\n\n" + user_msg
    contents = [
        full_text,
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
    ]
    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=_JUDGE_TEMPERATURE,
            response_mime_type="application/json",
            max_output_tokens=_JUDGE_MAX_TOKENS,
        ),
    )
    return resp.text or ""


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _median(values: List[float]) -> float:
    if not values:
        return 3.0
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _stddev(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


# ---------------------------------------------------------------------------
# Public Judge class
# ---------------------------------------------------------------------------


class Judge:
    def __init__(
        self,
        judge_model: str = "gpt-4o",
        api_key: Optional[str] = None,
        db_path: Optional[Path] = None,
        budget_remaining: float = 10.0,
        n_runs: int = _JUDGE_RUNS,
    ) -> None:
        self.judge_model = judge_model
        self.api_key = api_key or self._resolve_api_key(judge_model)
        self.db_path = db_path or Path("db/judge_cache.sqlite")
        self.budget_remaining = budget_remaining
        self.n_runs = n_runs
        self.total_cost_usd = 0.0
        self._system_msg, self._user_template_str = _load_prompt_parts()

    @staticmethod
    def _resolve_api_key(model: str) -> str:
        if "claude" in model or "anthropic" in model:
            return os.environ.get("ANTHROPIC_API_KEY", "")
        if "gemini" in model:
            return os.environ.get("GOOGLE_API_KEY", "")
        return os.environ.get("OPENAI_API_KEY", "")

    def _call_once(
        self,
        user_msg: str,
        image_b64: str,
        image_bytes: bytes,
    ) -> str:
        model = self.judge_model
        if "claude" in model or "anthropic" in model:
            return _call_anthropic(self._system_msg, user_msg, image_b64, model, self.api_key)
        if "gemini" in model:
            return _call_gemini(self._system_msg, user_msg, image_bytes, model, self.api_key)
        return _call_openai(self._system_msg, user_msg, image_b64, model, self.api_key)

    def _render_user_msg(self, case: TestCaseCard, prompt_used: str) -> str:
        si_block = _build_style_intent_block(case.style_intent)
        tmpl = Template(self._user_template_str)
        return tmpl.safe_substitute(
            prompt_used=prompt_used,
            style_intent_block=si_block,
        )

    def judge(
        self,
        case: TestCaseCard,
        prompt_used: str,
        screenshot_path: str,
    ) -> Optional[JudgeResult]:
        """Score a rendered scene. Returns None if judge is skipped or fails."""
        if case.judge_policy == JudgePolicy.SKIP:
            return None
        if not screenshot_path or not Path(screenshot_path).exists():
            logger.warning("Judge skipped for %s: no screenshot at %r", case.id, screenshot_path)
            return None
        if self.budget_remaining <= 0:
            logger.warning("Judge skipped for %s: budget exhausted", case.id)
            return None

        cache_key = _cache_key(prompt_used, screenshot_path, self.judge_model)
        cached = _get_cache(self.db_path, cache_key)
        if cached:
            logger.debug("Judge cache hit for %s", case.id)
            return JudgeResult.model_validate(cached)

        with open(screenshot_path, "rb") as f:
            image_bytes = f.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        user_msg = self._render_user_msg(case, prompt_used)

        raw_results: List[Dict[str, Any]] = []
        for i in range(self.n_runs):
            try:
                raw = self._call_once(user_msg, image_b64, image_bytes)
                parsed = _parse_raw_response(raw)
                raw_results.append(parsed)
            except Exception as exc:
                logger.warning("Judge run %d failed for %s: %s", i, case.id, exc)

        if not raw_results:
            logger.error("All judge runs failed for %s", case.id)
            return None

        mid = raw_results[len(raw_results) // 2]

        semantics = [r["semantic"] for r in raw_results]
        aesthetics = [r["aesthetic"] for r in raw_results]
        professionals = [r["professional"] for r in raw_results]

        result_dict: Dict[str, Any] = {
            "detected_style": mid["detected_style"],
            "detected_concept": mid["detected_concept"],
            "style_alignment_pass": mid["style_alignment_pass"],
            "concept_alignment_pass": mid["concept_alignment_pass"],
            "semantic": _median(semantics),
            "aesthetic": _median(aesthetics),
            "professional": _median(professionals),
            "stddev": _stddev(semantics + aesthetics + professionals),
            "judged_under_standard": mid["judged_under_standard"],
            "reasoning": mid["reasoning"],
            "confidence": _median([r["confidence"] for r in raw_results]),
            "raw_responses": [r.get("raw", {}) for r in raw_results],
        }

        _set_cache(self.db_path, cache_key, result_dict)
        return JudgeResult.model_validate(result_dict)
