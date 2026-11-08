"""Post-LLM rules that decide if an evaluation is worth persisting / notifying."""

from __future__ import annotations

from watchhunter.domain.evaluation import RarityLevel, Recommendation, WatchEvaluation


class DealEvaluator:
    """Gates evaluations by score + recommendation.

    The Gemini prompt has its own internal score-vs-interesting threshold which
    is independent of the operator-configured MIN_SCORE, so we deliberately do
    NOT check `ev.interesting` here — that would double-filter and effectively
    hide everything between MIN_SCORE and the prompt's hardcoded threshold.
    Score + recommendation are sufficient gates.
    """

    def __init__(self, *, min_score: int, min_rarity: str = "") -> None:
        self._min_score = min_score
        # Optional: only notify references at least this rare (e.g. "medium").
        self._min_rarity = RarityLevel(min_rarity) if min_rarity else None

    def is_promising(self, ev: WatchEvaluation) -> bool:
        if ev.recommendation == Recommendation.SKIP:
            return False
        if ev.score < self._min_score:
            return False
        if self._min_rarity is not None and ev.rarity.rank < self._min_rarity.rank:
            return False
        return True
