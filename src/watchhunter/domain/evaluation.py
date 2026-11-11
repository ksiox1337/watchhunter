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
    VERY_HIGH = "very_high"

    @property
    def rank(self) -> int:
        return list(RarityLevel).index(self)


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
    # Presentation fields (Russian). Optional so older stored evaluations load.
    display_name: str = ""
    era: str = ""
    rarity_note: str = ""
    value_low_eur: Decimal | None = None
    value_high_eur: Decimal | None = None
    story: str = ""
    why: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    # Evidence gathered for finds (see sales/, web check, photo index).
    web_low_eur: Decimal | None = None
    web_high_eur: Decimal | None = None
    web_examples: int = 0
    web_summary: str = ""
    web_sources: tuple[str, ...] = ()
    sales_sold: int = 0
    sales_unsold: int = 0
    sales_median_eur: Decimal | None = None
    photo_seen_url: str = ""
    # Your taste model: probability you'd mark this 👍/💸/💰; explore = sent
    # below the threshold on purpose, to keep learning.
    taste: float | None = None
    explore: bool = False
    raw_response: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_promising(self) -> bool:
        return (
            self.recommendation != Recommendation.SKIP
            and self.interesting
        )


def presentation_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Russian presentation fields from a stored/LLM raw response (missing → defaults)."""

    def dec(value: Any) -> Decimal | None:
        try:
            return Decimal(str(value)) if value is not None else None
        except ArithmeticError:
            return None

    def items(key: str) -> tuple[str, ...]:
        return tuple(str(x).strip() for x in raw.get(key) or [] if str(x).strip())

    return {
        "display_name": str(raw.get("display_name") or ""),
        "era": str(raw.get("era") or ""),
        "rarity_note": str(raw.get("rarity_note") or ""),
        "value_low_eur": dec(raw.get("value_low_eur")),
        "value_high_eur": dec(raw.get("value_high_eur")),
        "story": str(raw.get("story") or ""),
        "why": items("why"),
        "checks": items("checks"),
        "web_low_eur": dec((raw.get("web_check") or {}).get("sold_low_eur")) or None,
        "web_high_eur": dec((raw.get("web_check") or {}).get("sold_high_eur")) or None,
        "web_examples": int((raw.get("web_check") or {}).get("examples_found") or 0),
        "web_summary": str((raw.get("web_check") or {}).get("summary") or ""),
        "web_sources": tuple(str(u) for u in (raw.get("web_check") or {}).get("sources") or []),
        "sales_sold": int((raw.get("sales") or {}).get("sold") or 0),
        "sales_unsold": int((raw.get("sales") or {}).get("unsold") or 0),
        "sales_median_eur": dec((raw.get("sales") or {}).get("median")),
        "photo_seen_url": str((raw.get("photo_match") or {}).get("listing_url") or ""),
        "taste": (raw.get("taste") or {}).get("p"),
        "explore": bool((raw.get("taste") or {}).get("explore")),
    }
