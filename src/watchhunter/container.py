"""Dependency Injection composition root.

All adapters and use cases are instantiated here, in one place, with explicit
constructor wiring — no framework. Swap an adapter by editing one method.
"""

from __future__ import annotations

from dataclasses import dataclass

from watchhunter.application.ports.analyzer import AnalyzerPort
from watchhunter.application.ports.marketplace import MarketplacePort
from watchhunter.application.ports.notifier import NotifierPort
from watchhunter.application.ports.repository import ListingRepository
from watchhunter.application.services.deal_evaluator import DealEvaluator
from watchhunter.application.services.listing_filter import ListingFilter
from watchhunter.application.services.promising_notifier import PromisingNotifier
from watchhunter.application.use_cases.notify_promising import NotifyPromisingUseCase
from watchhunter.application.use_cases.scan_watches import ScanWatchesUseCase
from watchhunter.config.logging import get_logger
from watchhunter.config.settings import Settings
from watchhunter.costs.budget import BudgetGuard
from watchhunter.domain.models import BuyingOption, Marketplace
from watchhunter.infrastructure.ebay.adapter import EbayApiMarketplaceAdapter
from watchhunter.infrastructure.ebay.client import EbayBrowseClient
from watchhunter.infrastructure.ebay.html_adapter import EbayHtmlMarketplaceAdapter
from watchhunter.infrastructure.http.client import HttpClient
from watchhunter.infrastructure.jev.adapter import JevTriageAnalyzer
from watchhunter.infrastructure.kleinanzeigen.adapter import (
    KleinanzeigenMarketplaceAdapter,
)
from watchhunter.infrastructure.openai_api.adapter import OpenAIAnalyzerAdapter
from watchhunter.infrastructure.openai_api.client import OpenAIClient
from watchhunter.infrastructure.persistence.database import Database
from watchhunter.infrastructure.persistence.repository import SqlAlchemyListingRepository
from watchhunter.infrastructure.persistence.usage_repository import (
    GeminiUsageRepository,
)
from watchhunter.infrastructure.ratelimit.limiter import RateLimiter
from watchhunter.infrastructure.telegram.adapter import TelegramNotifierAdapter
from watchhunter.infrastructure.telegram.client import TelegramBotClient
from watchhunter.scheduler.scheduler import Scheduler

log = get_logger(__name__)


@dataclass
class Container:
    """Holds everything needed by main.py at runtime."""

    settings: Settings
    http: HttpClient
    database: Database
    repository: ListingRepository
    marketplace: MarketplacePort
    analyzer: AnalyzerPort
    notifier: NotifierPort
    scheduler: Scheduler

    async def aclose(self) -> None:
        await self.scheduler.shutdown()
        await self.http.close()
        await self.database.close()


async def build_container(settings: Settings) -> Container:
    settings.ensure_dirs()

    http = HttpClient()
    await http.start()

    database = Database(url=settings.database_url)
    await database.init()
    repository: ListingRepository = SqlAlchemyListingRepository(database)

    usage_repo = GeminiUsageRepository(database)
    cap = settings.max_daily_cost_usd
    budget = BudgetGuard(
        repository=usage_repo,
        max_daily_usd=cap if cap and cap > 0 else None,
        warn_at_pct=settings.budget_warn_at_pct,
    )
    log.info(
        "budget.configured",
        cap_usd=str(cap) if cap and cap > 0 else "unlimited",
    )

    marketplace = _build_marketplace(settings, http)
    analyzer = _build_analyzer(settings, http, budget)
    notifier = _build_notifier(settings, http)

    listing_filter = ListingFilter(
        ends_within_hours=settings.auction_ends_within_hours,
        max_price_eur=settings.max_price_eur,
        max_shipping_eur=settings.max_shipping_eur,
    )
    deal_evaluator = DealEvaluator(min_score=settings.min_score)
    promising_notifier = PromisingNotifier(
        notifier=notifier,
        marketplace=marketplace,
        repository=repository,
        max_price_eur=settings.max_price_eur,
        max_shipping_eur=settings.max_shipping_eur,
    )

    marketplaces = [Marketplace(m) for m in settings.ebay_marketplaces]

    scan_uc = ScanWatchesUseCase(
        marketplace=marketplace,
        analyzer=analyzer,
        repository=repository,
        listing_filter=listing_filter,
        deal_evaluator=deal_evaluator,
        promising_notifier=promising_notifier,
        marketplaces=marketplaces,
        category_ids=settings.ebay_category_ids,
        keywords=settings.ebay_keywords,
        ends_within_hours=settings.auction_ends_within_hours,
        reanalysis_ttl_hours=settings.reanalysis_ttl_hours,
        max_price_eur=settings.max_price_eur,
        gallery_max_images=settings.max_images_per_listing,
        concurrency=settings.eval_concurrency,
    )
    notify_uc = NotifyPromisingUseCase(
        repository=repository,
        promising_notifier=promising_notifier,
        min_score=settings.min_score,
    )
    kleinanzeigen_uc: ScanWatchesUseCase | None = None
    if settings.kleinanzeigen_enabled and settings.kleinanzeigen_keywords:
        ka_adapter = KleinanzeigenMarketplaceAdapter(
            http=http,
            rate_limiter=RateLimiter(
                rate_per_minute=settings.kleinanzeigen_rate_limit_rpm
            ),
            pages_per_query=settings.kleinanzeigen_pages_per_query,
        )
        ka_promising_notifier = PromisingNotifier(
            notifier=notifier,
            marketplace=ka_adapter,
            repository=repository,
            max_price_eur=settings.max_price_eur,
            max_shipping_eur=settings.max_shipping_eur,
        )
        kleinanzeigen_uc = ScanWatchesUseCase(
            marketplace=ka_adapter,
            analyzer=analyzer,
            repository=repository,
            listing_filter=listing_filter,
            deal_evaluator=deal_evaluator,
            promising_notifier=ka_promising_notifier,
            marketplaces=[Marketplace.KLEINANZEIGEN],
            category_ids=[],
            keywords=settings.kleinanzeigen_keywords,
            ends_within_hours=settings.auction_ends_within_hours,
            reanalysis_ttl_hours=settings.reanalysis_ttl_hours,
            max_price_eur=settings.max_price_eur,
            gallery_max_images=settings.max_images_per_listing,
        concurrency=settings.eval_concurrency,
            buying_option=BuyingOption.FIXED_PRICE,
            only_new=True,
            max_pages_per_query=settings.kleinanzeigen_pages_per_query,
            warmup_first_scan=settings.kleinanzeigen_warmup_on_start,
        )

    buy_now_uc: ScanWatchesUseCase | None = None
    if settings.buy_now_enabled and settings.buy_now_keywords:
        buy_now_uc = ScanWatchesUseCase(
            marketplace=marketplace,
            analyzer=analyzer,
            repository=repository,
            listing_filter=listing_filter,
            deal_evaluator=deal_evaluator,
            promising_notifier=promising_notifier,
            marketplaces=marketplaces,
            category_ids=settings.ebay_category_ids,
            keywords=settings.buy_now_keywords,
            ends_within_hours=settings.auction_ends_within_hours,
            reanalysis_ttl_hours=settings.reanalysis_ttl_hours,
            max_price_eur=settings.max_price_eur,
            gallery_max_images=settings.max_images_per_listing,
        concurrency=settings.eval_concurrency,
            buying_option=BuyingOption.FIXED_PRICE,
            only_new=True,
            max_pages_per_query=settings.buy_now_html_pages_per_query,
            warmup_first_scan=settings.buy_now_warmup_on_start,
        )

    scheduler = Scheduler(
        scan_use_case=scan_uc,
        notify_use_case=notify_uc,
        scan_interval_minutes=settings.scan_interval_minutes,
        notify_interval_minutes=settings.notify_interval_minutes,
        buy_now_use_case=buy_now_uc,
        buy_now_interval_minutes=settings.buy_now_scan_interval_minutes,
        buy_now_interval_seconds=settings.buy_now_scan_interval_seconds,
        kleinanzeigen_use_case=kleinanzeigen_uc,
        kleinanzeigen_interval_seconds=settings.kleinanzeigen_scan_interval_seconds,
    )

    return Container(
        settings=settings,
        http=http,
        database=database,
        repository=repository,
        marketplace=marketplace,
        analyzer=analyzer,
        notifier=notifier,
        scheduler=scheduler,
    )


# ─── factories ────────────────────────────────────────────────────────────
def _build_marketplace(settings: Settings, http: HttpClient) -> MarketplacePort:
    if settings.ebay_use_api and settings.ebay_client_id and settings.ebay_client_secret:
        log.info("container.marketplace", impl="ebay.api")
        client = EbayBrowseClient(
            client_id=settings.ebay_client_id,
            client_secret=settings.ebay_client_secret,
            oauth_url=settings.ebay_oauth_url,
            api_base_url=settings.ebay_api_base_url,
            http=http,
        )
        return EbayApiMarketplaceAdapter(
            client=client,
            rate_limiter=RateLimiter(rate_per_minute=60),
        )
    log.warning(
        "container.marketplace",
        impl="ebay.html_fallback",
        reason="EBAY_USE_API is false or credentials are missing",
    )
    return EbayHtmlMarketplaceAdapter(
        http=http,
        rate_limiter=RateLimiter(rate_per_minute=20),
        pages_per_query=settings.ebay_html_pages_per_query,
    )


def _build_analyzer(
    settings: Settings, http: HttpClient, budget: BudgetGuard
) -> AnalyzerPort:
    log.info(
        "container.analyzer",
        impl="openai",
        triage_model=settings.openai_triage_model,
        eval_model=settings.openai_model,
        batch=settings.triage_batch_size,
    )
    client = OpenAIClient(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        base_url=settings.openai_base_url or None,
        reasoning_effort=settings.openai_reasoning_effort,
        budget=budget,
    )
    openai_analyzer = OpenAIAnalyzerAdapter(
        client=client,
        http=http,
        rate_limiter=RateLimiter(rate_per_minute=settings.openai_rate_limit_rpm),
        triage_rate_limiter=RateLimiter(
            rate_per_minute=settings.openai_triage_rate_limit_rpm
        ),
        triage_model=settings.openai_triage_model,
        max_images=settings.max_images_per_listing,
        image_detail=settings.openai_image_detail,
        triage_batch_size=settings.triage_batch_size,
    )
    if settings.triage_provider.lower().strip() != "jev":
        return openai_analyzer
    if not settings.typesafe_api_key:
        log.warning("container.jev_disabled", reason="TYPESAFE_API_KEY is empty")
        return openai_analyzer
    log.info("container.triage", impl="jev", model=settings.jev_model,
             threshold=settings.jev_threshold)
    return JevTriageAnalyzer(
        api_key=settings.typesafe_api_key,
        http=http,
        evaluator=openai_analyzer,
        rate_limiter=RateLimiter(rate_per_minute=settings.jev_rate_limit_rpm),
        model=settings.jev_model,
        base_url=settings.jev_base_url,
        threshold=settings.jev_threshold,
        batch_size=settings.triage_batch_size,
        budget=budget,
    )


def _build_notifier(settings: Settings, http: HttpClient) -> NotifierPort:
    client = TelegramBotClient(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
        http=http,
    )
    return TelegramNotifierAdapter(client=client, timezone=settings.timezone)
