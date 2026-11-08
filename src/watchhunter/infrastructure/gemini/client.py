"""Gemini API client — wraps google-genai SDK with async helpers."""

from __future__ import annotations

import asyncio
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


class GeminiClient:
    """Async wrapper around `google.genai.Client.models.generate_content`.

    The google-genai SDK is sync-only for generate_content, so we run it in a
    thread to keep our scheduler async.

    Cost-aware: before each call, checks BudgetGuard against today's cap; after
    each call, records the real token usage reported by the API.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        budget: BudgetGuard | None = None,
    ) -> None:
        if not api_key:
            raise AnalyzerError("GEMINI_API_KEY is required")
        # Import lazily so missing key/sdk doesn't break unrelated imports.
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
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
        """Call Gemini and return parsed JSON. Retries on transient failures.

        `model` overrides the default model for this call (used to route the
        cheap triage step to gemini-2.5-flash while keeping pro for full eval).
        """
        from google.genai import types

        parts: list[Any] = [user_text]
        for data, mime in image_bytes:
            parts.append(
                types.Part.from_bytes(data=data, mime_type=mime)
            )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=0.2,
        )
        target_model = model or self._model

        # Pre-flight budget check (rough token estimate from prompt sizes;
        # actual usage recorded post-call).
        if self._budget is not None:
            est_in = (
                (len(system_instruction) + len(user_text)) // 4
                + len(image_bytes) * 258  # Gemini image tokenization
            )
            est_out = 400  # JSON eval responses are usually 200-500 tokens
            await self._budget.check(
                model=target_model,
                est_input_tokens=est_in,
                est_output_tokens=est_out,
            )

        captured: dict[str, Any] = {}

        def _call() -> dict[str, Any]:
            resp = self._client.models.generate_content(
                model=target_model,
                contents=parts,
                config=config,
            )
            # Stash real token usage for post-call recording.
            meta = getattr(resp, "usage_metadata", None)
            if meta is not None:
                captured["input_tokens"] = int(
                    getattr(meta, "prompt_token_count", 0) or 0
                )
                captured["output_tokens"] = int(
                    getattr(meta, "candidates_token_count", 0) or 0
                )
            # `parsed` is the validated structured response when response_schema is set.
            parsed = getattr(resp, "parsed", None)
            if isinstance(parsed, dict):
                return parsed
            text = (resp.text or "").strip()
            if not text:
                raise AnalyzerError("Empty Gemini response")
            import json
            try:
                return json.loads(text)  # type: ignore[no-any-return]
            except json.JSONDecodeError as exc:
                raise AnalyzerError(f"Gemini returned non-JSON: {text[:200]}") from exc

        def _is_rate_limited(exc: BaseException) -> bool:
            msg = str(exc)
            return "429" in msg or "RESOURCE_EXHAUSTED" in msg

        def _should_retry(exc: BaseException) -> bool:
            # Retry transient errors, but NEVER retry rate-limit responses —
            # they'd just burn the same quota window again.
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
                # Extract the specific quota dimension from the 429 body so we
                # can tell per-minute vs per-day vs project-level restrictions.
                msg = str(exc)
                quota_id = _extract_quota_id(msg)
                retry_after = _extract_retry_after(msg)
                log.warning(
                    "gemini.rate_limited",
                    model=target_model,
                    quota_id=quota_id,
                    retry_after_s=retry_after,
                )
                raise BudgetExhaustedError(
                    f"Gemini {target_model} rate-limited (429): "
                    f"quota={quota_id}  retry_in={retry_after}s"
                ) from exc
            raise AnalyzerError(
                f"Gemini call failed for model {target_model}: {exc}"
            ) from exc
        raise AnalyzerError("Gemini exhausted retries")


# ─── 429 introspection ───────────────────────────────────────────────────
import re

_QUOTA_ID_RE = re.compile(r"quotaId['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]")
_RETRY_AFTER_RE = re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+)s")


def _extract_quota_id(msg: str) -> str:
    m = _QUOTA_ID_RE.search(msg)
    return m.group(1) if m else "unknown"


def _extract_retry_after(msg: str) -> int:
    m = _RETRY_AFTER_RE.search(msg)
    return int(m.group(1)) if m else 0
