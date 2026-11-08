from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from watchhunter.application.services.listing_filter import ListingFilter
from watchhunter.domain.models import Listing, Marketplace


def _make_listing(*, bid_count: int, hours: float, with_images: bool = True) -> Listing:
    return Listing(
        external_id="x",
        marketplace=Marketplace.EBAY_DE,
        title="t",
        description="",
        url="https://www.ebay.de/itm/1",  # type: ignore[arg-type]
        current_price=Decimal("1"),
        currency="EUR",
        current_price_eur=Decimal("1"),
        bid_count=bid_count,
        end_time=datetime.now(timezone.utc) + timedelta(hours=hours),
        image_urls=("https://i/1.jpg",) if with_images else (),  # type: ignore[arg-type]
    )


def test_rejects_no_bids() -> None:
    f = ListingFilter(ends_within_hours=24)
    assert not f.is_eligible(_make_listing(bid_count=0, hours=3))


def test_rejects_too_far_in_future() -> None:
    f = ListingFilter(ends_within_hours=24)
    assert not f.is_eligible(_make_listing(bid_count=2, hours=48))


def test_rejects_past_auction() -> None:
    f = ListingFilter(ends_within_hours=24)
    assert not f.is_eligible(_make_listing(bid_count=2, hours=-1))


def test_rejects_no_images() -> None:
    f = ListingFilter(ends_within_hours=24)
    assert not f.is_eligible(_make_listing(bid_count=2, hours=3, with_images=False))


def test_accepts_eligible() -> None:
    f = ListingFilter(ends_within_hours=24)
    assert f.is_eligible(_make_listing(bid_count=1, hours=5))
