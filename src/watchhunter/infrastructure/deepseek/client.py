"""DeepSeek API client.

DeepSeek uses an OpenAI-compatible chat-completions endpoint at
https://api.deepseek.com/v1. We use the official `openai` SDK pointed at that
host instead of writing our own HTTP shim — keeps retry, streaming, and auth
behavior consistent with what the SDK already does.

Cost-aware: budget check before the call, real usage recorded after.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from watchhunter.config.logging import get_logger
from watchhunter.costs.budget import BudgetGuard
from watchhunter.domain.exceptions import AnalyzerError, BudgetExhaustedError

log = get_logger(__name__)

_BASE_URL = "https://api.deepseek.com/v1"


class DeepSeekClient:
    """Async wrapper around the DeepSeek chat-completions API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        budget: BudgetGuard | None = None,
    ) -> None:
        if not api_key:
            raise AnalyzerError("DEEPSEEK_API_KEY is required")
        from openai import OpenAI  # imported lazily

        self._client = OpenAI(api_key=api_key, base_url=_BASE_URL)
        self._model = model
        self._budget = budget

    async def generate_json(
        self,
        *,
        system_instruction: str,
        user_text: str,
        image_bytes: list[tuple[bytes, str]],
        response_schema: dict[str, Any],
        model: str | None = None,
    ) -> dict[str, Any]:
        target_model = model or self._model

        # DeepSeek's OpenAI-compatible /chat/completions endpoint is TEXT-ONLY
        # — `image_url` content blocks are rejected with 400. We strip images
        # and rely on title + description signal instead. The eval prompt
        # explicitly tells the model when images are unavailable.
        if image_bytes:
            log.debug(
                "deepseek.images_dropped",
                model=target_model,
                count=len(image_bytes),
                reason="endpoint_text_only",
            )

        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_text},
        ]

        # Pre-flight budget check.
        if self._budget is not None:
            est_in = (
                (len(system_instruction) + len(user_text)) // 4
                + len(image_bytes) * 258
            )
            est_out = 400
            await self._budget.check(
                model=target_model,
                est_input_tokens=est_in,
                est_output_tokens=est_out,
            )

        captured: dict[str, Any] = {}

        def _call() -> dict[str, Any]:
            # DeepSeek supports OpenAI-style `json_object` mode, not the
            # newer `json_schema` strict mode. The model relies on the system
            # prompt to specify the expected schema (ours does — see prompts.py).
            resp = self._client.chat.completions.create(
                model=target_model,
                messages=messages,  # type: ignore[arg-type]
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            # Token accounting from usage metadata.
            usage = getattr(resp, "usage", None)
            if usage is not None:
                captured["input_tokens"] = int(getattr(usage, "prompt_tokens", 0) or 0)
                captured["output_tokens"] = int(
                    getattr(usage, "completion_tokens", 0) or 0
                )
            text = resp.choices[0].message.content or ""
            text = text.strip()
            if not text:
                raise AnalyzerError("Empty DeepSeek response")
            try:
                return json.loads(text)  # type: ignore[no-any-return]
            except json.JSONDecodeError as exc:
                raise AnalyzerError(
                    f"DeepSeek returned non-JSON: {text[:200]}"
                ) from exc

        def _is_rate_limited(exc: BaseException) -> bool:
            msg = str(exc)
            return "429" in msg or "rate_limit" in msg.lower() or "quota" in msg.lower()

        def _should_retry(exc: BaseException) -> bool:
            return not _is_rate_limited(exc)

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(min=2, max=20),
                retry=retry_if_exception(_should_retry),
                reraise=True,
            ):
                with attempt:
                    result = await asyncio.to_thread(_call)
                    if self._budget is not None and captured:
                        await self._budget.record(
                            model=target_model,
                            input_tokens=captured.get("input_tokens", 0),
                            output_tokens=captured.get("output_tokens", 0),
                        )
                    return result
        except Exception as exc:
            if _is_rate_limited(exc):
                log.warning("deepseek.rate_limited", model=target_model)
                raise BudgetExhaustedError(
                    f"DeepSeek {target_model} rate-limited: {str(exc)[:200]}"
                ) from exc
            raise AnalyzerError(
                f"DeepSeek call failed for model {target_model}: {exc}"
            ) from exc
        raise AnalyzerError("DeepSeek exhausted retries")
