"""AnalyzerPort implementation backed by DeepSeek V4 multimodal.

Mirrors the structure of GeminiAnalyzerAdapter — same prompts, same triage→
eval funnel, same image-download approach. The only differences are wrapped
inside DeepSeekClient (OpenAI-compatible API instead of google-genai SDK).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

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
from watchhunter.infrastructure.deepseek.client import DeepSeekClient
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


class DeepSeekAnalyzerAdapter(AnalyzerPort):
    def __init__(
        self,
        *,
        client: DeepSeekClient,
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

    # ─── triage (text-only) ──────────────────────────────────────────────
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
            return TriageResult(interesting=False, reason="budget_exhausted")
        except AnalyzerError:
            return TriageResult(interesting=True, reason="triage_error_passthrough")

        try:
            return TriageResult(
                interesting=bool(raw["interesting"]),
                reason=str(raw.get("reason") or ""),
            )
        except (KeyError, ValueError):
            return TriageResult(interesting=True, reason="triage_malformed_passthrough")

    # ─── text-only evaluation (DeepSeek endpoint is not multimodal) ──────
    async def evaluate(self, listing: Listing) -> WatchEvaluation:
        # DeepSeek's OpenAI-compatible endpoint rejects image content blocks.
        # We skip the image download entirely — saves bandwidth and Pro time.
        user_prompt = build_user_prompt(
            title=listing.title,
            description=listing.description,
            current_price_eur=f"{listing.current_price_eur:.2f}",
            original_price=f"{listing.current_price:.2f}",
            original_currency=listing.currency,
            bid_count=listing.bid_count,
            hours_left=listing.hours_until_end,
            has_images=False,
        )

        async with self._rate:
            raw = await self._client.generate_json(
                system_instruction=SYSTEM_INSTRUCTION,
                user_text=user_prompt,
                image_bytes=[],
                response_schema=RESPONSE_SCHEMA,
            )

        return _to_evaluation(raw)


def _to_evaluation(raw: dict[str, Any]) -> WatchEvaluation:
    """Tolerant parser.

    DeepSeek's `json_object` mode doesn't enforce the schema, so the model
    occasionally drops optional fields. We default missing values to sensible
    no-ops (low score, "skip", low confidence) so the eval pipeline doesn't
    crash on a partial response.
    """

    def _enum(value: Any, cls: type, default: Any) -> Any:
        try:
            return cls(str(value).lower())
        except (ValueError, AttributeError):
            return default

    def _dec(value: Any, default: str = "0") -> Decimal:
        try:
            return Decimal(str(value)) if value is not None else Decimal(default)
        except Exception:
            return Decimal(default)

    def _int(value: Any, default: int = 0) -> int:
        try:
            return int(value) if value is not None else default
        except (ValueError, TypeError):
            return default

    try:
        return WatchEvaluation(
            interesting=bool(raw.get("interesting", False)),
            score=max(0, min(100, _int(raw.get("score"), 0))),
            brand=str(raw.get("brand") or "Unknown"),
            model=str(raw.get("model") or "Unknown"),
            confidence=max(0, min(100, _int(raw.get("confidence"), 50))),
            estimated_market_value_eur=_dec(raw.get("estimated_market_value_eur")),
            current_price_eur=_dec(raw.get("current_price_eur")),
            potential_profit_eur=_dec(raw.get("potential_profit_eur")),
            rarity=_enum(raw.get("rarity"), RarityLevel, RarityLevel.LOW),
            condition=str(raw.get("condition") or "unknown"),
            fake_risk=_enum(raw.get("fake_risk"), FakeRisk, FakeRisk.MEDIUM),
            recommendation=_enum(
                raw.get("recommendation"), Recommendation, Recommendation.SKIP
            ),
            reasoning=str(raw.get("reasoning") or ""),
            raw_response=raw,
        )
    except Exception as exc:
        raise AnalyzerError(f"Malformed DeepSeek evaluation: {exc}") from exc
