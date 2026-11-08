"""Port for any auction marketplace (eBay, Chrono24, …)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

from watchhunter.domain.models import BuyingOption, Listing, Marketplace


@dataclass(frozen=True)
class ListingState:
    """Live snapshot of a listing's current price + shipping, both EUR-normalised.

    Either field can be None:
      price_eur is None    → listing has ended / been removed
      shipping_eur is None → shipping wasn't parseable from the item page
    """

    price_eur: Decimal | None
    shipping_eur: Decimal | None


@dataclass(frozen=True)
class MarketplaceQuery:
    """Search parameters passed to a marketplace adapter."""

    marketplace: Marketplace
    category_id: str | None
    keywords: list[str]
    ends_within_hours: int
    only_with_bids: bool = True
    max_price_eur: Decimal | None = None
    buying_option: BuyingOption = BuyingOption.AUCTION
    max_pages: int | None = None  # override the adapter's default page count


class MarketplacePort(ABC):
    """Abstract marketplace adapter — yields auction listings."""

    @abstractmethod
    def search_auctions(self, query: MarketplaceQuery) -> AsyncIterator[Listing]:
        """Yield listings matching the query. MUST be an async generator."""
        raise NotImplementedError

    @abstractmethod
    async def refresh_state(self, listing: Listing) -> ListingState:
        """Re-fetch the listing's current price + shipping cost in EUR.

        Used at notify-time to verify that what we promise the user still
        matches reality on eBay before we send the Telegram message.
        """
        raise NotImplementedError

    @abstractmethod
    async def fetch_gallery(self, listing: Listing, max_images: int) -> tuple[str, ...]:
        """Fetch additional image URLs from the listing's item page.

        Returns a tuple of high-res image URLs (may be empty). Best-effort —
        callers should treat failure as "no additional images".
        """
        raise NotImplementedError
