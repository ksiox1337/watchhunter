"""Core domain entities — pure, immutable, framework-agnostic."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Marketplace(StrEnum):
    EBAY_US = "EBAY_US"
    EBAY_DE = "EBAY_DE"
    EBAY_GB = "EBAY_GB"
    EBAY_FR = "EBAY_FR"
    EBAY_IT = "EBAY_IT"
    KLEINANZEIGEN = "KLEINANZEIGEN"


class BuyingOption(StrEnum):
    AUCTION = "auction"
    FIXED_PRICE = "fixed_price"


class Listing(BaseModel):
    """An auction listing surfaced by a marketplace adapter."""

    model_config = ConfigDict(frozen=True)

    external_id: str = Field(..., description="Unique listing ID at the source marketplace.")
    marketplace: Marketplace
    title: str
    description: str = ""
    url: HttpUrl
    current_price: Decimal
    currency: str = Field(..., min_length=3, max_length=3)
    current_price_eur: Decimal
    bid_count: int = Field(ge=0)
    end_time: datetime = Field(..., description="Auction end time in UTC.")
    image_urls: tuple[HttpUrl, ...] = ()
    buying_option: BuyingOption = BuyingOption.AUCTION
    # Best-effort shipping cost in EUR; None when not parseable.
    # 0 means explicitly free shipping ("Kostenloser Versand" / "Free shipping").
    shipping_cost_eur: Decimal | None = None

    @property
    def hours_until_end(self) -> float:
        return (self.end_time - datetime.now(timezone.utc)).total_seconds() / 3600.0

    @property
    def dedup_key(self) -> str:
        return f"{self.marketplace.value}:{self.external_id}"
