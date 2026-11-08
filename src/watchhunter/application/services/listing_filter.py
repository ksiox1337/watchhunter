"""Stateless rules that decide if a listing is worth analyzing."""

from __future__ import annotations

from decimal import Decimal

from watchhunter.domain.models import BuyingOption, Listing


class ListingFilter:
    """Cheap filters applied BEFORE calling the (expensive) analyzer.

    Auction mode: requires bids, end within window.
    Fixed-price mode: requires neither — only price + image checks apply.
    Both modes: max-price + max-shipping checks.
    """

    def __init__(
        self,
        *,
        ends_within_hours: int,
        max_price_eur: Decimal | None = None,
        max_shipping_eur: Decimal | None = None,
    ) -> None:
        self._ends_within_hours = ends_within_hours
        self._max_price_eur = max_price_eur
        self._max_shipping_eur = max_shipping_eur

    def is_eligible(self, listing: Listing) -> bool:
        if not listing.image_urls:
            return False
        if (
            self._max_price_eur is not None
            and listing.current_price_eur > self._max_price_eur
        ):
            return False
        # Shipping cap: only enforced when we actually parsed a value.
        # Unknown shipping is allowed through — better to over-analyze than
        # silently drop real bargains.
        if (
            self._max_shipping_eur is not None
            and listing.shipping_cost_eur is not None
            and listing.shipping_cost_eur > self._max_shipping_eur
        ):
            return False

        if listing.buying_option == BuyingOption.AUCTION:
            if listing.bid_count <= 0:
                return False
            hours_left = listing.hours_until_end
            if hours_left <= 0:
                return False
            if hours_left > self._ends_within_hours:
                return False
        return True
