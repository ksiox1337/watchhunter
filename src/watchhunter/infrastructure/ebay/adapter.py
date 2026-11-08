"""MarketplacePort implementation backed by the eBay Browse API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

from watchhunter.application.ports.marketplace import (
    ListingState,
    MarketplacePort,
    MarketplaceQuery,
)
from watchhunter.config.logging import get_logger
from watchhunter.domain.exceptions import MarketplaceError
from watchhunter.domain.models import Listing
from watchhunter.infrastructure.ebay.client import EbayBrowseClient
from watchhunter.infrastructure.ebay.currency import to_eur
from watchhunter.infrastructure.ebay.mappers import parse_summary
from watchhunter.infrastructure.ratelimit.limiter import RateLimiter

log = get_logger(__name__)


class EbayApiMarketplaceAdapter(MarketplacePort):
    """Yields auction listings from the eBay Browse API."""

    def __init__(
        self,
        *,
        client: EbayBrowseClient,
        rate_limiter: RateLimiter,
        page_size: int = 100,
        max_pages: int = 3,
    ) -> None:
        self._client = client
        self._rate = rate_limiter
        self._page_size = page_size
        self._max_pages = max_pages

    async def fetch_gallery(
        self, listing: Listing, max_images: int
    ) -> tuple[str, ...]:
        try:
            async with self._rate:
                data = await self._client.get_item(
                    listing.external_id, listing.marketplace.value
                )
        except MarketplaceError as exc:
            log.warning(
                "ebay.api.gallery_failed",
                external_id=listing.external_id,
                error=str(exc),
            )
            return ()

        images: list[str] = []
        primary = (data.get("image") or {}).get("imageUrl")
        if primary:
            images.append(str(primary))
        for extra in data.get("additionalImages") or []:
            if isinstance(extra, dict) and extra.get("imageUrl"):
                u = str(extra["imageUrl"])
                if u not in images:
                    images.append(u)
        return tuple(images[:max_images])

    async def refresh_state(self, listing: Listing) -> ListingState:
        try:
            async with self._rate:
                data = await self._client.get_item(
                    listing.external_id, listing.marketplace.value
                )
        except MarketplaceError as exc:
            msg = str(exc)
            if "404" in msg or "not found" in msg.lower():
                return ListingState(price_eur=None, shipping_eur=None)
            log.warning(
                "ebay.api.refresh_failed",
                external_id=listing.external_id,
                error=msg,
            )
            return ListingState(
                price_eur=listing.current_price_eur,
                shipping_eur=listing.shipping_cost_eur,
            )

        # Price
        bid = data.get("currentBidPrice") or data.get("price") or {}
        val = bid.get("value")
        currency = (bid.get("currency") or "EUR").upper()
        price = (
            to_eur(Decimal(str(val)), currency)
            if val is not None
            else listing.current_price_eur
        )

        # Shipping — take the first option's cost (Browse API lists multiple).
        shipping = listing.shipping_cost_eur
        for opt in data.get("shippingOptions") or []:
            cost = opt.get("shippingCost") if isinstance(opt, dict) else None
            if isinstance(cost, dict) and cost.get("value") is not None:
                shipping = to_eur(
                    Decimal(str(cost["value"])),
                    (cost.get("currency") or "EUR").upper(),
                )
                break

        return ListingState(price_eur=price, shipping_eur=shipping)

    async def search_auctions(
        self, query: MarketplaceQuery
    ) -> AsyncIterator[Listing]:
        seen: set[str] = set()
        for keyword in query.keywords:
            for page in range(self._max_pages):
                async with self._rate:
                    payload = await self._client.search(
                        marketplace_id=query.marketplace.value,
                        query=keyword,
                        category_id=query.category_id,
                        ends_within_hours=query.ends_within_hours,
                        max_price=(
                            float(query.max_price_eur)
                            if query.max_price_eur is not None
                            else None
                        ),
                        price_currency="EUR",
                        limit=self._page_size,
                        offset=page * self._page_size,
                    )
                items = payload.get("itemSummaries") or []
                if not items:
                    break
                for item in items:
                    listing = parse_summary(item, query.marketplace)
                    if not listing:
                        continue
                    if query.only_with_bids and listing.bid_count <= 0:
                        continue
                    if listing.dedup_key in seen:
                        continue
                    seen.add(listing.dedup_key)
                    yield listing
                if len(items) < self._page_size:
                    break
        log.info(
            "ebay.api.scan.done",
            marketplace=query.marketplace.value,
            yielded=len(seen),
        )
