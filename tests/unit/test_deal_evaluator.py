from __future__ import annotations

from decimal import Decimal

from watchhunter.application.services.deal_evaluator import DealEvaluator
from watchhunter.domain.evaluation import (
    FakeRisk,
    RarityLevel,
    Recommendation,
    WatchEvaluation,
)


def _ev(*, score: int, rec: Recommendation, interesting: bool = True) -> WatchEvaluation:
    return WatchEvaluation(
        interesting=interesting,
        score=score,
        brand="X",
        model="Y",
        confidence=80,
        estimated_market_value_eur=Decimal("200"),
        current_price_eur=Decimal("100"),
        potential_profit_eur=Decimal("100"),
        rarity=RarityLevel.MEDIUM,
        condition="good",
        fake_risk=FakeRisk.LOW,
        recommendation=rec,
        reasoning="ok",
    )


def test_skips_low_score() -> None:
    de = DealEvaluator(min_score=60)
    assert not de.is_promising(_ev(score=50, rec=Recommendation.BUY))


def test_skips_skip_recommendation() -> None:
    de = DealEvaluator(min_score=60)
    assert not de.is_promising(_ev(score=90, rec=Recommendation.SKIP))


def test_accepts_even_when_not_interesting_flag() -> None:
    # `interesting` is set by the prompt's own threshold (~60); MIN_SCORE is
    # the operator's gate. We intentionally don't double-check `interesting`.
    de = DealEvaluator(min_score=50)
    assert de.is_promising(_ev(score=55, rec=Recommendation.WATCH, interesting=False))


def test_accepts_promising() -> None:
    de = DealEvaluator(min_score=60)
    assert de.is_promising(_ev(score=80, rec=Recommendation.BUY))
    assert de.is_promising(_ev(score=60, rec=Recommendation.WATCH))
