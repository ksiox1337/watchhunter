"""MarketplacePort implementation backed by the eBay Browse API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal

from watchhunter.application.ports.marketplace import (
    ListingState,
    MarketplacePort,
    MarketplaceQuery,
)
from watchhunter.config.logging import get_logger
from watchhunter.domain.exceptions import MarketplaceError
from watchhunter.domain.models import BuyingOption, Listing
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
        page_size: int = 200,
        max_pages: int = 3,
    ) -> None:
        self._client = client
        self._rate = rate_limiter
        self._page_size = page_size
        self._max_pages = max_pages

    async def fetch_gallery(
        self, listing: Listing, max_images: int
    ) -> tuple[str, ...]:
        # Search summaries already carry image + additionalImages; only ask
        # for the item when they gave fewer than we want.
        if len(listing.image_urls) >= max_images:
            return tuple(str(u) for u in listing.image_urls[:max_images])
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

        # Ended or sold out: the API still returns the item (with its final
        # price), so treat it as gone for notifications.
        avail = (data.get("estimatedAvailabilities") or [{}])[0]
        end = data.get("itemEndDate")
        ended = avail.get("estimatedAvailabilityStatus") == "OUT_OF_STOCK" or (
            end and datetime.fromisoformat(end.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
        )
        if ended and listing.buying_option != BuyingOption.AUCTION:
            return ListingState(price_eur=None, shipping_eur=None)

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

        bids = data.get("bidCount")
        return ListingState(
            price_eur=price,
            shipping_eur=shipping,
            bid_count=int(bids) if bids is not None else None,
        )

    async def search_auctions(
        self, query: MarketplaceQuery
    ) -> AsyncIterator[Listing]:
        seen: set[str] = set()
        fixed = query.buying_option == BuyingOption.FIXED_PRICE
        pages = query.max_pages if query.max_pages is not None else self._max_pages
        for q in _group_keywords(query.keywords):
            for page in range(max(1, pages)):
                async with self._rate:
                    payload = await self._client.search(
                        marketplace_id=query.marketplace.value,
                        query=q,
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
                        fixed_price=fixed,
                    )
                items = payload.get("itemSummaries") or []
                for item in items:
                    listing = parse_summary(item, query.marketplace)
                    if not listing:
                        continue
                    if not fixed and query.only_with_bids and listing.bid_count <= 0:
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


def _group_keywords(keywords: list[str]) -> list[str]:
    """One-word keywords go into a single OR query: `(casio, seiko, pulsar)`.

    The Browse API ORs comma-separated words in parentheses, which saves one
    call per keyword against the 5000 calls/day quota. Multi-word phrases are
    not ORed reliably by eBay, so each stays its own query.
    """
    # "|" inside a keyword is an OR list (commas would split the .env CSV):
    # "casio (lcd|digital)" -> "casio (lcd, digital)" = casio AND (lcd OR digital).
    keywords = [k.replace("|", ", ") for k in keywords]
    words = [k.strip() for k in keywords if k.strip() and " " not in k.strip()]
    phrases = [k.strip() for k in keywords if " " in k.strip()]
    grouped: list[str] = []
    for i in range(0, len(words), 10):
        chunk = words[i : i + 10]
        grouped.append(chunk[0] if len(chunk) == 1 else f"({', '.join(chunk)})")
    return grouped + phrases
