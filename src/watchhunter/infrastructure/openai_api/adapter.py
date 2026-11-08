"""AnalyzerPort backed by OpenAI: batched text triage + multimodal evaluation."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from decimal import Decimal
from typing import Any

import aiohttp
import openai

from watchhunter.application.ports.analyzer import AnalyzerPort, TriageResult
from watchhunter.config.logging import get_logger
from watchhunter.domain.evaluation import (
    FakeRisk,
    RarityLevel,
    Recommendation,
    WatchEvaluation,
    presentation_fields,
)
from watchhunter.domain.exceptions import AnalyzerError, BudgetExhaustedError
from watchhunter.domain.models import Listing
from watchhunter.infrastructure.http.client import HttpClient
from watchhunter.infrastructure.llm.prompts import (
    CARD_SCHEMA,
    CARD_SUFFIX,
    RESPONSE_SCHEMA,
    SCREEN_SCHEMA,
    SCREEN_SUFFIX,
    SYSTEM_INSTRUCTION,
    TRIAGE_BATCH_SCHEMA,
    TRIAGE_INSTRUCTION,
    TRIAGE_SCHEMA,
    VERDICT_SCHEMA,
    VERDICT_SUFFIX,
    build_card_prompt,
    build_triage_batch_prompt,
    build_triage_prompt,
    build_user_prompt,
)
from watchhunter.infrastructure.openai_api.client import OpenAIClient
from watchhunter.infrastructure.ratelimit.limiter import RateLimiter

log = get_logger(__name__)


class OpenAIAnalyzerAdapter(AnalyzerPort):
    def __init__(
        self,
        *,
        client: OpenAIClient,
        http: HttpClient,
        rate_limiter: RateLimiter,
        triage_rate_limiter: RateLimiter,
        triage_model: str,
        max_images: int = 4,
        image_detail: str = "low",
        triage_batch_size: int = 25,
        screen_model: str = "",
        screen_pass_score: int = 50,
        card_min_score: int | None = None,
    ) -> None:
        self._client = client
        self._http = http
        self._rate = rate_limiter
        self._triage_rate = triage_rate_limiter
        self._triage_model = triage_model
        self._max_images = max_images
        self._image_detail = image_detail
        self._batch_size = max(1, triage_batch_size)
        # Cascade: a cheap vision model screens first; only listings it scores
        # >= screen_pass_score (and doesn't skip) get the full evaluation.
        self._screen_model = screen_model
        self._screen_pass = screen_pass_score
        # Two-step evaluation: verdict for every listing, Russian card text
        # only when the verdict could be sent (score >= card_min_score, not
        # skip). None = one combined call (old behaviour).
        self._card_min = card_min_score

    # ─── triage: one listing ─────────────────────────────────────────────
    async def triage(self, listing: Listing) -> TriageResult:
        prompt = build_triage_prompt(title=listing.title, description=listing.description)
        try:
            async with self._triage_rate:
                raw = await self._client.generate_json(
                    system_instruction=TRIAGE_INSTRUCTION,
                    user_content=prompt,
                    schema_name="triage",
                    response_schema=TRIAGE_SCHEMA,
                    model=self._triage_model,
                    est_output_tokens=40,
                )
        except BudgetExhaustedError:
            return TriageResult(interesting=False, reason="budget_exhausted")
        except (AnalyzerError, openai.OpenAIError):
            # Don't silently drop a potentially good listing.
            return TriageResult(interesting=True, reason="triage_error_passthrough")
        return TriageResult(
            interesting=bool(raw.get("interesting", True)),
            reason=str(raw.get("reason") or ""),
        )

    # ─── triage: many listings, one call per batch ───────────────────────
    async def triage_many(self, listings: list[Listing]) -> list[TriageResult]:
        """Judge listings in batches: the ~600-token instruction is paid once per
        batch instead of once per listing, and there are ~batch_size times fewer calls."""
        chunks = [
            listings[i : i + self._batch_size]
            for i in range(0, len(listings), self._batch_size)
        ]
        results = await asyncio.gather(*(self._triage_chunk(c) for c in chunks))
        return [r for chunk in results for r in chunk]

    async def _triage_chunk(self, chunk: list[Listing]) -> list[TriageResult]:
        if len(chunk) == 1:
            return [await self.triage(chunk[0])]
        prompt = build_triage_batch_prompt(
            [(str(i), lst.title, lst.description) for i, lst in enumerate(chunk)]
        )
        try:
            async with self._triage_rate:
                raw = await self._client.generate_json(
                    system_instruction=TRIAGE_INSTRUCTION,
                    user_content=prompt,
                    schema_name="triage_batch",
                    response_schema=TRIAGE_BATCH_SCHEMA,
                    model=self._triage_model,
                    est_output_tokens=25 * len(chunk),
                )
        except BudgetExhaustedError:
            return [TriageResult(False, "budget_exhausted") for _ in chunk]
        except (AnalyzerError, openai.OpenAIError) as exc:
            log.warning("triage.batch_failed", size=len(chunk), error=str(exc)[:200])
            return list(await asyncio.gather(*(self.triage(lst) for lst in chunk)))

        by_id: dict[str, TriageResult] = {}
        for item in raw.get("items") or []:
            with contextlib.suppress(KeyError, TypeError):
                by_id[str(item["id"]).strip("[] ")] = TriageResult(
                    interesting=bool(item["interesting"]),
                    reason=str(item.get("reason") or ""),
                )
        missing = [i for i in range(len(chunk)) if str(i) not in by_id]
        if missing:
            # Rare: the model skipped an id. Ask again for those alone.
            log.info("triage.batch_missing", missing=len(missing), size=len(chunk))
            redo = await asyncio.gather(*(self.triage(chunk[i]) for i in missing))
            for i, res in zip(missing, redo, strict=True):
                by_id[str(i)] = res
        return [by_id[str(i)] for i in range(len(chunk))]

    # ─── full multimodal evaluation ──────────────────────────────────────
    async def evaluate(self, listing: Listing) -> WatchEvaluation:
        urls = [str(u) for u in listing.image_urls][: self._max_images]
        text = build_user_prompt(
            title=listing.title,
            description=listing.description,
            current_price_eur=f"{listing.current_price_eur:.2f}",
            original_price=f"{listing.current_price:.2f}",
            original_currency=listing.currency,
            bid_count=listing.bid_count,
            hours_left=listing.hours_until_end,
            has_images=bool(urls),
        )

        if self._screen_model:
            screen = await self._with_image_fallback(
                lambda u: self._evaluate_call(text, u, mode="screen"), urls
            )
            score = int(screen.get("score") or 0)
            if screen.get("recommendation") == "skip" or score < self._screen_pass:
                log.info(
                    "eval.screened_out",
                    score=score,
                    brand=screen.get("brand"),
                    model=screen.get("model"),
                )
                return _from_screen(screen, listing)

        if self._card_min is None:
            raw = await self._with_image_fallback(
                lambda u: self._evaluate_call(text, u, mode="full"), urls
            )
            return _to_evaluation(raw)

        verdict = await self._with_image_fallback(
            lambda u: self._evaluate_call(text, u, mode="verdict"), urls
        )
        score = int(verdict.get("score") or 0)
        if verdict.get("recommendation") != "skip" and score >= self._card_min:
            card_text = build_card_prompt(text, json.dumps(verdict, ensure_ascii=False))
            try:
                card = await self._with_image_fallback(
                    lambda u: self._evaluate_call(card_text, u, mode="card"), urls
                )
                verdict = {**verdict, **card}
            except AnalyzerError as exc:
                # The find still goes out, just with a plainer card.
                log.warning("eval.card_failed", error=str(exc)[:200])
        return _to_evaluation(verdict)

    async def _with_image_fallback(self, call: Any, urls: list[str]) -> dict[str, Any]:
        # Fast path: hand OpenAI the public image URLs, no download on our side.
        try:
            return await call(urls)  # type: ignore[no-any-return]
        except openai.BadRequestError as exc:
            # Usually an image URL OpenAI could not fetch (hotlink block, 404).
            # Retry once with the images we can download ourselves.
            log.info("eval.url_images_rejected", error=str(exc)[:200])
            data_urls = await self._download_as_data_urls(urls)
            try:
                return await call(data_urls)  # type: ignore[no-any-return]
            except openai.OpenAIError as exc2:
                raise AnalyzerError(f"OpenAI evaluation failed: {exc2}") from exc2

    async def _evaluate_call(
        self, text: str, image_urls: list[str], *, mode: str = "full"
    ) -> dict[str, Any]:
        """mode: full | verdict | card | screen (see the schemas in llm/prompts.py)."""
        suffix, name, schema, out = {
            "full": ("", "watch_evaluation", RESPONSE_SCHEMA, 600),
            "verdict": (VERDICT_SUFFIX, "watch_verdict", VERDICT_SCHEMA, 250),
            "card": (CARD_SUFFIX, "watch_card", CARD_SCHEMA, 350),
            "screen": (SCREEN_SUFFIX, "watch_screen", SCREEN_SCHEMA, 120),
        }[mode]
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        content += [
            {"type": "image_url", "image_url": {"url": u, "detail": self._image_detail}}
            for u in image_urls
        ]
        async with self._rate:
            return await self._client.generate_json(
                system_instruction=SYSTEM_INSTRUCTION + suffix,
                user_content=content,
                schema_name=name,
                response_schema=schema,
                model=self._screen_model if mode == "screen" else None,
                est_output_tokens=out,
                image_count=len(image_urls),
                image_detail=self._image_detail,
            )

    async def _download_as_data_urls(self, urls: list[str]) -> list[str]:
        async def fetch(url: str) -> str | None:
            with contextlib.suppress(aiohttp.ClientError, asyncio.TimeoutError):
                async with self._http.session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    mime = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
                    if not mime.startswith("image/"):
                        mime = "image/jpeg"
                    data = await resp.read()
                    return f"data:{mime};base64,{base64.b64encode(data).decode()}"
            return None

        results = await asyncio.gather(*(fetch(u) for u in urls))
        return [r for r in results if r]


def _to_evaluation(raw: dict[str, Any]) -> WatchEvaluation:
    try:
        return WatchEvaluation(
            interesting=bool(raw["interesting"]),
            score=max(0, min(100, int(raw["score"]))),
            brand=str(raw.get("brand") or "Unknown"),
            model=str(raw.get("model") or "Unknown"),
            confidence=max(0, min(100, int(raw["confidence"]))),
            estimated_market_value_eur=Decimal(str(raw["estimated_market_value_eur"])),
            current_price_eur=Decimal(str(raw["current_price_eur"])),
            potential_profit_eur=Decimal(str(raw["potential_profit_eur"])),
            rarity=RarityLevel(str(raw["rarity"]).lower()),
            condition=str(raw.get("condition") or "unknown"),
            fake_risk=FakeRisk(str(raw["fake_risk"]).lower()),
            recommendation=Recommendation(str(raw["recommendation"]).lower()),
            reasoning=str(raw.get("reasoning") or ""),
            **presentation_fields(raw),
            raw_response=raw,
        )
    except (KeyError, ValueError) as exc:
        raise AnalyzerError(f"Malformed evaluation: {exc}") from exc



def _from_screen(raw: dict[str, Any], listing: Listing) -> WatchEvaluation:
    """A screened-out listing as a (rejected) evaluation, so it is stored and skipped."""
    try:
        value = Decimal(str(raw.get("estimated_market_value_eur") or 0))
        return WatchEvaluation(
            interesting=False,
            score=max(0, min(100, int(raw.get("score") or 0))),
            brand=str(raw.get("brand") or "Unknown"),
            model=str(raw.get("model") or "Unknown"),
            confidence=0,
            estimated_market_value_eur=value,
            current_price_eur=listing.current_price_eur,
            potential_profit_eur=value - listing.current_price_eur,
            rarity=RarityLevel.LOW,
            condition="",
            fake_risk=FakeRisk(str(raw.get("fake_risk") or "medium").lower()),
            recommendation=Recommendation.SKIP,
            reasoning=f"screen: {raw.get('reasoning') or ''}",
            raw_response={"screen": raw},
        )
    except (KeyError, ValueError) as exc:
        raise AnalyzerError(f"Malformed screen result: {exc}") from exc
