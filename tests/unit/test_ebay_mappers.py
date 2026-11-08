from __future__ import annotations

from decimal import Decimal

from watchhunter.domain.models import Marketplace
from watchhunter.infrastructure.ebay.mappers import parse_summary


def test_parse_summary_happy_path() -> None:
    item = {
        "itemId": "v1|123|0",
        "title": "Omega Seamaster Vintage",
        "shortDescription": "Original dial, working",
        "itemWebUrl": "https://www.ebay.com/itm/123",
        "price": {"value": "1234.50", "currency": "USD"},
        "bidCount": 7,
        "itemEndDate": "2026-06-07T10:00:00.000Z",
        "image": {"imageUrl": "https://i.ebayimg.com/1.jpg"},
        "additionalImages": [{"imageUrl": "https://i.ebayimg.com/2.jpg"}],
    }
    listing = parse_summary(item, Marketplace.EBAY_US)
    assert listing is not None
    assert listing.external_id == "v1|123|0"
    assert listing.bid_count == 7
    assert listing.currency == "USD"
    assert listing.current_price == Decimal("1234.50")
    assert listing.current_price_eur > 0
    assert len(listing.image_urls) == 2


def test_parse_summary_missing_required_returns_none() -> None:
    assert parse_summary({}, Marketplace.EBAY_US) is None
    assert parse_summary({"itemId": "1", "title": "x"}, Marketplace.EBAY_US) is None
