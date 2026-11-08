"""Hybrid AnalyzerPort — different backends for triage vs deep evaluation.

The bot's pipeline has two analyzer calls with very different cost/quality
profiles:

  • Triage  — text only, 8000+ calls/day, needs to be cheap. Vision unnecessary.
  • Eval    — multimodal, ~250 calls/day, needs vision for condition + fakes.

This wrapper lets the operator pick a different provider for each. Typical
config: DeepSeek text-only for triage (cheap, no daily cap) + Gemini Flash-
Lite for eval (vision, ~$0.0003/call).
"""

from __future__ import annotations

from watchhunter.application.ports.analyzer import AnalyzerPort, TriageResult
from watchhunter.config.logging import get_logger
from watchhunter.domain.evaluation import WatchEvaluation
from watchhunter.domain.models import Listing

log = get_logger(__name__)


class HybridAnalyzerAdapter(AnalyzerPort):
    def __init__(
        self,
        *,
        triage_analyzer: AnalyzerPort,
        eval_analyzer: AnalyzerPort,
    ) -> None:
        self._triage = triage_analyzer
        self._eval = eval_analyzer

    async def triage(self, listing: Listing) -> TriageResult:
        return await self._triage.triage(listing)

    async def evaluate(self, listing: Listing) -> WatchEvaluation:
        return await self._eval.evaluate(listing)
