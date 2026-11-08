"""BudgetGuard — protects you from runaway Gemini spend.

Used by the Gemini client. Before every call:
  1. Estimate the call's cost from the model's pricing.
  2. Check: today's spend + estimated cost > MAX_DAILY_COST_USD?
        → raise BudgetExhaustedError; caller treats as a soft failure.
  3. Otherwise let the call proceed.

After every call, the client reports the real token usage via `record(...)`,
which persists to SQLite. Budget state survives restarts.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from watchhunter.config.logging import get_logger
from watchhunter.costs.pricing import estimate_cost_usd
from watchhunter.domain.exceptions import BudgetExhaustedError
from watchhunter.infrastructure.persistence.usage_repository import (
    GeminiUsageRepository,
)

log = get_logger(__name__)


class BudgetGuard:
    """Tracks Gemini spend against a daily cap. Thread-safe via a lock."""

    def __init__(
        self,
        *,
        repository: GeminiUsageRepository,
        max_daily_usd: Decimal | None,
        warn_at_pct: float = 80.0,
    ) -> None:
        self._repo = repository
        self._max = max_daily_usd
        self._warn_at = warn_at_pct
        self._lock = asyncio.Lock()
        # In-process cache of today's spend to avoid hitting SQLite per call.
        self._today_total: Decimal = Decimal("0")
        self._cache_date: str = ""
        self._warned = False

    @property
    def enabled(self) -> bool:
        return self._max is not None and self._max > 0

    async def _refresh_cache(self) -> Decimal:
        async with self._lock:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if today != self._cache_date:
                self._cache_date = today
                self._warned = False
            self._today_total = await self._repo.total_cost_today_utc()
            return self._today_total

    async def check(
        self,
        *,
        model: str,
        est_input_tokens: int,
        est_output_tokens: int,
    ) -> None:
        """Raise BudgetExhaustedError if the call would push us over today's cap."""
        if not self.enabled:
            return

        if not self._cache_date:
            await self._refresh_cache()

        est_cost = estimate_cost_usd(model, est_input_tokens, est_output_tokens)
        projected = self._today_total + est_cost

        if projected > self._max:  # type: ignore[operator]
            log.warning(
                "budget.exhausted",
                cap_usd=str(self._max),
                today_usd=f"{self._today_total:.4f}",
                est_cost_usd=f"{est_cost:.4f}",
            )
            raise BudgetExhaustedError(
                f"Daily Gemini cap ${self._max:.2f} would be exceeded "
                f"(today=${self._today_total:.4f}, est=${est_cost:.4f})"
            )

        if (
            not self._warned
            and self._max is not None
            and projected / self._max * 100 >= Decimal(str(self._warn_at))
        ):
            log.warning(
                "budget.warning",
                pct=f"{projected / self._max * 100:.1f}",
                today_usd=f"{self._today_total:.4f}",
                cap_usd=str(self._max),
            )
            self._warned = True

    async def record(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Persist actual usage from the response."""
        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        await self._repo.record(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        # Keep in-memory cache in sync without re-reading from DB.
        async with self._lock:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if today != self._cache_date:
                self._cache_date = today
                self._today_total = Decimal("0")
                self._warned = False
            self._today_total += cost

    async def today_usd(self) -> Decimal:
        if not self._cache_date:
            await self._refresh_cache()
        return self._today_total

    async def remaining_usd(self) -> Decimal | None:
        if not self.enabled:
            return None
        await self.today_usd()
        return max(Decimal("0"), self._max - self._today_total)  # type: ignore[operator]
