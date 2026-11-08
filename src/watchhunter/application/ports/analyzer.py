"""Port for any LLM-based watch analyzer (Gemini, OpenAI, …)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from watchhunter.domain.evaluation import WatchEvaluation
from watchhunter.domain.models import Listing


@dataclass(frozen=True)
class TriageResult:
    """Cheap text-only verdict — used to decide if a listing deserves a deep analysis."""

    interesting: bool
    reason: str


class AnalyzerPort(ABC):
    """Evaluates a single listing and returns a structured evaluation."""

    @abstractmethod
    async def triage(self, listing: Listing) -> TriageResult:
        """Text-only quick judgement: is this listing worth the multimodal call?"""
        raise NotImplementedError

    @abstractmethod
    async def evaluate(self, listing: Listing) -> WatchEvaluation:
        """Full multimodal evaluation using the listing's photos."""
        raise NotImplementedError
