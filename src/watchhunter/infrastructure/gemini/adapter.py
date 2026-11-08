"""AnalyzerPort implementation backed by Gemini multimodal."""

from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal
from typing import Any

import aiohttp

from watchhunter.application.ports.analyzer import AnalyzerPort, TriageResult
from watchhunter.config.logging import get_logger
from watchhunter.domain.evaluation import (
    FakeRisk,
    RarityLevel,
    Recommendation,
    WatchEvaluation,
)
from watchhunter.domain.exceptions import AnalyzerError, BudgetExhaustedError
from watchhunter.domain.models import Listing
from watchhunter.infrastructure.gemini.client import GeminiClient
from watchhunter.infrastructure.gemini.prompts import (
    RESPONSE_SCHEMA,
    SYSTEM_INSTRUCTION,
    TRIAGE_INSTRUCTION,
    TRIAGE_SCHEMA,
    build_triage_prompt,
    build_user_prompt,
)
from watchhunter.infrastructure.http.client import HttpClient
from watchhunter.infrastructure.ratelimit.limiter import RateLimiter

log = get_logger(__name__)


class GeminiAnalyzerAdapter(AnalyzerPort):
    def __init__(
        self,
        *,
        client: GeminiClient,
        http: HttpClient,
        rate_limiter: RateLimiter,
        triage_rate_limiter: RateLimiter,
        triage_model: str,
        max_images: int = 4,
    ) -> None:
        self._client = client
        self._http = http
        self._rate = rate_limiter
        self._triage_rate = triage_rate_limiter
        self._triage_model = triage_model
        self._max_images = max_images

    # ─── triage (text-only, cheap) ───────────────────────────────────────
    async def triage(self, listing: Listing) -> TriageResult:
        prompt = build_triage_prompt(
            title=listing.title,
            description=listing.description,
        )
        try:
            async with self._triage_rate:
                raw = await self._client.generate_json(
                    system_instruction=TRIAGE_INSTRUCTION,
                    user_text=prompt,
                    image_bytes=[],
                    response_schema=TRIAGE_SCHEMA,
                    model=self._triage_model,
                )
        except BudgetExhaustedError:
            # Cap hit. Don't pretend the item is interesting (avoid spending
            # downstream); the scan use case treats this as a soft "skip".
            return TriageResult(interesting=False, reason="budget_exhausted")
        except AnalyzerError:
            # If triage fails for any reason, default to "interesting" so we
            # don't silently drop a potentially good listing.
            return TriageResult(interesting=True, reason="triage_error_passthrough")

        try:
            return TriageResult(
                interesting=bool(raw["interesting"]),
                reason=str(raw.get("reason") or ""),
            )
        except (KeyError, ValueError):
            return TriageResult(interesting=True, reason="triage_malformed_passthrough")

    # ─── full multimodal evaluation ──────────────────────────────────────
    async def evaluate(self, listing: Listing) -> WatchEvaluation:
        image_bytes = await self._download_images(listing)

        user_prompt = build_user_prompt(
            title=listing.title,
            description=listing.description,
            current_price_eur=f"{listing.current_price_eur:.2f}",
            original_price=f"{listing.current_price:.2f}",
            original_currency=listing.currency,
            bid_count=listing.bid_count,
            hours_left=listing.hours_until_end,
        )

        async with self._rate:
            raw = await self._client.generate_json(
                system_instruction=SYSTEM_INSTRUCTION,
                user_text=user_prompt,
                image_bytes=image_bytes,
                response_schema=RESPONSE_SCHEMA,
            )

        return _to_evaluation(raw)

    async def _download_images(self, listing: Listing) -> list[tuple[bytes, str]]:
        urls = list(listing.image_urls)[: self._max_images]
        if not urls:
            return []

        sem = asyncio.Semaphore(4)

        async def fetch(url_obj: Any) -> tuple[bytes, str] | None:
            url = str(url_obj)
            async with sem:
                with contextlib.suppress(aiohttp.ClientError, asyncio.TimeoutError):
                    async with self._http.session.get(url) as resp:
                        if resp.status != 200:
                            return None
                        mime = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
                        if not mime.startswith("image/"):
                            mime = "image/jpeg"
                        data = await resp.read()
                        return data, mime
            return None

        results = await asyncio.gather(*(fetch(u) for u in urls))
        return [r for r in results if r is not None]


def _to_evaluation(raw: dict[str, Any]) -> WatchEvaluation:
    """Validate Gemini's response into the domain type."""
    try:
        return WatchEvaluation(
            interesting=bool(raw["interesting"]),
            score=int(raw["score"]),
            brand=str(raw.get("brand") or "Unknown"),
            model=str(raw.get("model") or "Unknown"),
            confidence=int(raw["confidence"]),
            estimated_market_value_eur=Decimal(str(raw["estimated_market_value_eur"])),
            current_price_eur=Decimal(str(raw["current_price_eur"])),
            potential_profit_eur=Decimal(str(raw["potential_profit_eur"])),
            rarity=RarityLevel(str(raw["rarity"]).lower()),
            condition=str(raw.get("condition") or "unknown"),
            fake_risk=FakeRisk(str(raw["fake_risk"]).lower()),
            recommendation=Recommendation(str(raw["recommendation"]).lower()),
            reasoning=str(raw.get("reasoning") or ""),
            raw_response=raw,
        )
    except (KeyError, ValueError) as exc:
        raise AnalyzerError(f"Malformed Gemini evaluation: {exc}") from exc
