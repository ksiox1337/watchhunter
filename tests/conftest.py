"""Shared pytest fixtures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from watchhunter.domain.evaluation import (
    FakeRisk,
    RarityLevel,
    Recommendation,
    WatchEvaluation,
)
from watchhunter.domain.models import Listing, Marketplace


@pytest.fixture
def sample_listing() -> Listing:
    return Listing(
        external_id="123456789",
        marketplace=Marketplace.EBAY_DE,
        title="Vintage Seiko 6139 Pogue Chronograph",
        description="Original dial, working chronograph",
        url="https://www.ebay.de/itm/123456789",  # type: ignore[arg-type]
        current_price=Decimal("180.00"),
        currency="EUR",
        current_price_eur=Decimal("180.00"),
        bid_count=4,
        end_time=datetime.now(timezone.utc) + timedelta(hours=5),
        image_urls=("https://i.ebayimg.com/test1.jpg",),  # type: ignore[arg-type]
    )


@pytest.fixture
def sample_evaluation() -> WatchEvaluation:
    return WatchEvaluation(
        interesting=True,
        score=82,
        brand="Seiko",
        model="6139 Pogue",
        confidence=88,
        estimated_market_value_eur=Decimal("550.00"),
        current_price_eur=Decimal("180.00"),
        potential_profit_eur=Decimal("370.00"),
        rarity=RarityLevel.MEDIUM,
        condition="good",
        fake_risk=FakeRisk.LOW,
        recommendation=Recommendation.BUY,
        reasoning="Original dial confirmed by photos, asymmetric bezel correct for era.",
    )
