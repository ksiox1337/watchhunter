"""Watch evaluation domain types — the structured output the analyzer must produce."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Recommendation(StrEnum):
    BUY = "buy"
    WATCH = "watch"
    SKIP = "skip"


class RarityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FakeRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class WatchEvaluation(BaseModel):
    """Validated structured output from the analyzer adapter."""

    model_config = ConfigDict(frozen=True)

    interesting: bool
    score: int = Field(ge=0, le=100)
    brand: str
    model: str
    confidence: int = Field(ge=0, le=100)
    estimated_market_value_eur: Decimal
    current_price_eur: Decimal
    potential_profit_eur: Decimal
    rarity: RarityLevel
    condition: str
    fake_risk: FakeRisk
    recommendation: Recommendation
    reasoning: str
    raw_response: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_promising(self) -> bool:
        return (
            self.recommendation != Recommendation.SKIP
            and self.interesting
        )
