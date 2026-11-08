"""Scan all marketplaces, run cheap filters, analyze, and persist promising hits."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

from watchhunter.application.ports.analyzer import AnalyzerPort
from watchhunter.application.ports.marketplace import (
    MarketplacePort,
    MarketplaceQuery,
)
from watchhunter.application.ports.repository import ListingRepository
from watchhunter.application.services.deal_evaluator import DealEvaluator
from watchhunter.application.services.listing_filter import ListingFilter
from watchhunter.application.services.promising_notifier import PromisingNotifier
from watchhunter.config.logging import get_logger
from watchhunter.domain.exceptions import AnalyzerError, MarketplaceError
from watchhunter.domain.models import BuyingOption, Listing, Marketplace

log = get_logger(__name__)


class ScanWatchesUseCase:
    """Orchestrates marketplace fetch → filter → analyze → persist."""

    def __init__(
        self,
        *,
        marketplace: MarketplacePort,
        analyzer: AnalyzerPort,
        repository: ListingRepository,
        listing_filter: ListingFilter,
        deal_evaluator: DealEvaluator,
        promising_notifier: PromisingNotifier,
        marketplaces: list[Marketplace],
        category_ids: list[str],
        keywords: list[str],
        ends_within_hours: int,
        reanalysis_ttl_hours: int,
        max_price_eur: Decimal | None = None,
        gallery_max_images: int = 4,
        concurrency: int = 3,
        buying_option: BuyingOption = BuyingOption.AUCTION,
        only_new: bool = False,
        max_pages_per_query: int | None = None,
        warmup_first_scan: bool = False,
    ) -> None:
        self._marketplace = marketplace
        self._analyzer = analyzer
        self._repo = repository
        self._filter = listing_filter
        self._evaluator = deal_evaluator
        self._push_notifier = promising_notifier
        self._marketplaces = marketplaces
        self._category_ids = category_ids or [None]  # type: ignore[list-item]
        self._keywords = keywords
        self._ends_within_hours = ends_within_hours
        self._reanalysis_ttl_hours = reanalysis_ttl_hours
        self._max_price_eur = max_price_eur
        self._gallery_max_images = gallery_max_images
        self._buying_option = buying_option
        self._only_new = only_new
        self._max_pages_per_query = max_pages_per_query
        # Warmup is one-shot in-memory: first scan after process start records
        # what's already up without analyzing, so only NEW arrivals trigger work.
        self._warmup_pending = warmup_first_scan and only_new
        self._semaphore = asyncio.Semaphore(concurrency)
        # Titles don't change, so a "not interesting" verdict holds: remember it
        # in memory for the re-analysis window instead of paying triage again on
        # every scan (auctions are re-listed by eBay search every 15 min).
        self._triaged_out: dict[str, float] = {}

    async def execute(self) -> dict[str, int]:
        stats = {
            "fetched": 0,
            "filtered_out": 0,
            "already_notified": 0,
            "triaged_out": 0,
            "analyzed": 0,
            "promising": 0,
            "pushed": 0,
            "warmed_up": 0,
            "errors": 0,
        }
        seen_ids: set[str] = set()

        # Warmup: silently record everything currently listed so future scans
        # only act on items that genuinely appeared after process start.
        if self._warmup_pending:
            listed = await self._warmup(stats)
            # A warmup that saw nothing (marketplace blocked or down) recorded
            # nothing; keep it pending, or the next scan would treat every
            # existing listing as brand new.
            self._warmup_pending = listed == 0
            log.info("scan.warmup_done", **stats)
            return stats

        eligible: list[Listing] = []

        async def fetch(marketplace: Marketplace, category_id: str | None) -> list[Listing]:
            query = MarketplaceQuery(
                marketplace=marketplace,
                category_id=category_id if isinstance(category_id, str) else None,
                keywords=self._keywords,
                ends_within_hours=self._ends_within_hours,
                only_with_bids=self._buying_option == BuyingOption.AUCTION,
                max_price_eur=self._max_price_eur,
                buying_option=self._buying_option,
                max_pages=self._max_pages_per_query,
            )
            found: list[Listing] = []
            try:
                async for listing in self._marketplace.search_auctions(query):
                    found.append(listing)
            except MarketplaceError as exc:
                log.error(
                    "scan.marketplace_error",
                    marketplace=marketplace.value,
                    error=str(exc),
                )
                stats["errors"] += 1
            return found

        # All (marketplace, category) searches run at once; the adapter's rate
        # limiter still paces the HTTP requests.
        batches = await asyncio.gather(
            *(fetch(m, c) for m in self._marketplaces for c in self._category_ids)
        )
        for listing in (lst for batch in batches for lst in batch):
            stats["fetched"] += 1
            if listing.external_id in seen_ids:
                continue
            seen_ids.add(listing.external_id)
            if not self._filter.is_eligible(listing):
                stats["filtered_out"] += 1
                continue
            eligible.append(listing)

        # Order the work so the right items get analyzed first — this matters
        # because tasks acquire the concurrency semaphore in creation order and,
        # under the daily budget cap, the earliest tasks are the ones guaranteed
        # to get spend.
        #
        #   AUCTION: ending soonest first. eBay sorts each keyword's results by
        #     end time (_sop=1), but the per-(marketplace, keyword) streams above
        #     are interleaved, so the merged set isn't globally ordered. Re-sort
        #     by end_time to spend on the lots closest to closing.
        #   FIXED_PRICE (Buy-It-Now / Kleinanzeigen): freshest first. eBay returns
        #     newly-listed first (_sop=10) and fetch order preserves that, so we
        #     leave it untouched — there's no meaningful end_time to sort on.
        if self._buying_option == BuyingOption.AUCTION:
            eligible.sort(key=lambda listing: listing.end_time)

        # 1. Cheap local checks (DB dedup, triage memory), in parallel.
        keep = await asyncio.gather(*(self._needs_work(lst, stats) for lst in eligible))
        todo = [lst for lst, k in zip(eligible, keep, strict=True) if k]

        # 2. Batched text triage: many titles per model call.
        verdicts = await self._analyzer.triage_many(todo) if todo else []
        passed = []
        for listing, verdict in zip(todo, verdicts, strict=True):
            if verdict.interesting:
                passed.append((listing, verdict.reason))
                continue
            stats["triaged_out"] += 1
            if verdict.reason != "budget_exhausted":
                self._remember_triaged_out(listing.external_id)
                if self._only_new:
                    await self._repo.upsert_listing(listing)
            log.info(
                "scan.triaged_out",
                external_id=listing.external_id,
                reason=verdict.reason,
                title=listing.title[:80],
            )

        # 3. Gallery + multimodal evaluation for the few that passed, in parallel.
        if passed:
            await asyncio.gather(
                *(self._process_one(lst, reason, stats) for lst, reason in passed)
            )

        log.info("scan.complete", **stats)
        return stats

    async def _warmup(self, stats: dict[str, int]) -> int:
        """First-scan-after-startup pass: record every listing as 'seen' without
        analyzing any of them. Cheap (no LLM calls, no item-page fetches)."""
        seen: set[str] = set()
        for marketplace in self._marketplaces:
            for category_id in self._category_ids:
                query = MarketplaceQuery(
                    marketplace=marketplace,
                    category_id=category_id if isinstance(category_id, str) else None,
                    keywords=self._keywords,
                    ends_within_hours=self._ends_within_hours,
                    only_with_bids=False,
                    max_price_eur=self._max_price_eur,
                    buying_option=self._buying_option,
                    max_pages=self._max_pages_per_query,
                )
                try:
                    async for listing in self._marketplace.search_auctions(query):
                        if listing.external_id in seen:
                            continue
                        seen.add(listing.external_id)
                        if await self._repo.was_ever_seen(listing.external_id):
                            continue
                        await self._repo.upsert_listing(listing)
                        stats["warmed_up"] += 1
                except MarketplaceError as exc:
                    log.error(
                        "scan.warmup_marketplace_error",
                        marketplace=marketplace.value,
                        error=str(exc),
                    )
                    stats["errors"] += 1
        return len(seen)

    def _remember_triaged_out(self, external_id: str) -> None:
        now = time.monotonic()
        self._triaged_out[external_id] = now
        if len(self._triaged_out) > 50_000:
            cutoff = now - self._reanalysis_ttl_hours * 3600
            self._triaged_out = {k: t for k, t in self._triaged_out.items() if t > cutoff}

    async def _needs_work(self, listing: Listing, stats: dict[str, int]) -> bool:
        """False when the listing was already handled — no model call needed."""
        try:
            seen_at = self._triaged_out.get(listing.external_id)
            if seen_at is not None and (
                time.monotonic() - seen_at < self._reanalysis_ttl_hours * 3600
            ):
                stats["triaged_out"] += 1
                return False
            # Fresh-only mode (BIN): if we've ever seen it, it wasn't a steal.
            if self._only_new and await self._repo.was_ever_seen(listing.external_id):
                stats["already_notified"] += 1
                return False
            if await self._repo.was_ever_notified(listing.external_id):
                stats["already_notified"] += 1
                return False
            recent = await self._repo.get_recent_evaluation(
                listing.external_id, self._reanalysis_ttl_hours
            )
            return recent is None
        except Exception as exc:
            log.exception("scan.precheck_error", external_id=listing.external_id, error=str(exc))
            stats["errors"] += 1
            return False

    async def _process_one(
        self, listing: Listing, triage_reason: str, stats: dict[str, int]
    ) -> None:
        async with self._semaphore:
            try:
                # ── Stage 2a: enrich with full gallery from item page ────
                gallery = ()
                try:
                    gallery = await self._marketplace.fetch_gallery(
                        listing, self._gallery_max_images
                    )
                except Exception as exc:
                    log.warning(
                        "scan.gallery_failed",
                        external_id=listing.external_id,
                        error=str(exc),
                    )

                enriched_images = _merge_images(
                    listing.image_urls, gallery, self._gallery_max_images
                )
                if enriched_images != listing.image_urls:
                    listing = listing.model_copy(
                        update={"image_urls": enriched_images}
                    )
                log.info(
                    "scan.enriched",
                    external_id=listing.external_id,
                    images=len(enriched_images),
                    triage_reason=triage_reason,
                )

                # ── Stage 2b: full multimodal evaluation ─────────────────
                evaluation = await self._analyzer.evaluate(listing)
                stats["analyzed"] += 1

                if not self._evaluator.is_promising(evaluation):
                    log.info(
                        "scan.discarded",
                        external_id=listing.external_id,
                        score=evaluation.score,
                        recommendation=evaluation.recommendation.value,
                        brand=evaluation.brand,
                        model=evaluation.model,
                    )
                    # Rejected evaluations aren't stored, so remember the
                    # verdict in memory: no new photo evaluation every scan.
                    self._remember_triaged_out(listing.external_id)
                    # In fresh-only mode, record the listing so we never
                    # re-analyze it on the next scan.
                    if self._only_new:
                        await self._repo.upsert_listing(listing)
                    return

                listing_id = await self._repo.upsert_listing(listing)
                evaluation_id = await self._repo.save_evaluation(
                    listing_id, evaluation
                )
                stats["promising"] += 1
                log.info(
                    "scan.promising",
                    external_id=listing.external_id,
                    score=evaluation.score,
                    brand=evaluation.brand,
                    model=evaluation.model,
                )

                # ── Push-on-save: deliver to Telegram immediately, with
                # the same verify-price logic the periodic backstop uses.
                outcome = await self._push_notifier.notify_one(
                    listing, evaluation, evaluation_id
                )
                if outcome == "sent":
                    stats["pushed"] += 1
                log.info(
                    "scan.pushed",
                    external_id=listing.external_id,
                    outcome=outcome,
                )
            except AnalyzerError as exc:
                log.warning(
                    "scan.analyzer_error",
                    external_id=listing.external_id,
                    error=str(exc),
                )
                stats["errors"] += 1
            except Exception as exc:
                log.exception(
                    "scan.unexpected_error",
                    external_id=listing.external_id,
                    error=str(exc),
                )
                stats["errors"] += 1


def _merge_images(
    existing: tuple, extra: tuple[str, ...], limit: int
) -> tuple:
    """Combine the search-result thumbnail with item-page gallery, dedup, cap."""
    seen: set[str] = set()
    out: list = []
    for u in (*existing, *extra):
        s = str(u)
        if s in seen:
            continue
        seen.add(s)
        out.append(u if not isinstance(u, str) else u)
        if len(out) >= limit:
            break
    return tuple(out)
