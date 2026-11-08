"""OpenAI Chat Completions client: strict JSON output, budget-aware, async.

Works with any OpenAI-compatible endpoint (set OPENAI_BASE_URL), but the
defaults target api.openai.com with the gpt-5 nano/mini family.

Cost levers handled here:
  • Static text first (system prompt), variable text last — OpenAI caches a
    repeated prefix of >= 1024 tokens automatically and bills it at ~10%.
  • reasoning_effort (gpt-5 family): "minimal" skips most hidden reasoning
    tokens, which are billed as output and add seconds per call.
  • Real usage incl. cached tokens is recorded for the BudgetGuard.
"""

from __future__ import annotations

import json
from typing import Any

import openai
from openai import AsyncOpenAI

from watchhunter.config.logging import get_logger
from watchhunter.costs.budget import BudgetGuard
from watchhunter.domain.exceptions import AnalyzerError, BudgetExhaustedError

log = get_logger(__name__)

# Rough token cost of one image at detail="low" (fixed size tile).
LOW_DETAIL_IMAGE_TOKENS = 85
HIGH_DETAIL_IMAGE_TOKENS = 765


class OpenAIClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        reasoning_effort: str | None = "minimal",
        budget: BudgetGuard | None = None,
        timeout_s: float = 90.0,
    ) -> None:
        if not api_key:
            raise AnalyzerError("OPENAI_API_KEY is required")
        # The SDK retries 408/409/429/5xx and connection errors with backoff.
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
            timeout=timeout_s,
            max_retries=3,
        )
        self._model = model
        self._reasoning_effort = reasoning_effort or None
        self._budget = budget

    async def generate_json(
        self,
        *,
        system_instruction: str,
        user_content: str | list[dict[str, Any]],
        schema_name: str,
        response_schema: dict[str, Any],
        model: str | None = None,
        est_output_tokens: int = 400,
        image_count: int = 0,
        image_detail: str = "low",
    ) -> dict[str, Any]:
        target_model = model or self._model

        if self._budget is not None:
            text_len = len(system_instruction) + (
                len(user_content)
                if isinstance(user_content, str)
                else sum(len(p.get("text", "")) for p in user_content)
            )
            per_image = (
                LOW_DETAIL_IMAGE_TOKENS if image_detail == "low" else HIGH_DETAIL_IMAGE_TOKENS
            )
            await self._budget.check(
                model=target_model,
                est_input_tokens=text_len // 4 + image_count * per_image,
                est_output_tokens=est_output_tokens,
            )

        kwargs: dict[str, Any] = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": response_schema,
                },
            },
        }
        if self._reasoning_effort and _supports_reasoning_effort(target_model):
            kwargs["reasoning_effort"] = self._reasoning_effort

        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except openai.RateLimitError as exc:
            # Still 429 after the SDK's retries; insufficient_quota lands here too.
            log.warning("openai.rate_limited", model=target_model, error=str(exc)[:200])
            raise BudgetExhaustedError(f"OpenAI {target_model} rate-limited: {exc}") from exc
        except openai.BadRequestError:
            raise  # caller may retry differently (e.g. images it could not fetch)
        except openai.OpenAIError as exc:
            raise AnalyzerError(f"OpenAI call failed for {target_model}: {exc}") from exc

        usage = resp.usage
        if usage is not None:
            cached = 0
            details = getattr(usage, "prompt_tokens_details", None)
            if details is not None:
                cached = int(getattr(details, "cached_tokens", 0) or 0)
            log.debug(
                "openai.usage",
                model=target_model,
                prompt=usage.prompt_tokens,
                cached=cached,
                completion=usage.completion_tokens,
            )
            if self._budget is not None:
                await self._budget.record(
                    model=target_model,
                    input_tokens=int(usage.prompt_tokens or 0),
                    output_tokens=int(usage.completion_tokens or 0),
                    cached_input_tokens=cached,
                )

        choice = resp.choices[0]
        if getattr(choice.message, "refusal", None):
            raise AnalyzerError(f"OpenAI refused: {choice.message.refusal}")
        text = (choice.message.content or "").strip()
        if not text:
            raise AnalyzerError(f"Empty OpenAI response (finish={choice.finish_reason})")
        try:
            return json.loads(text)  # type: ignore[no-any-return]
        except json.JSONDecodeError as exc:
            raise AnalyzerError(f"OpenAI returned non-JSON: {text[:200]}") from exc


def _supports_reasoning_effort(model: str) -> bool:
    m = model.lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4")) and "chat" not in m
