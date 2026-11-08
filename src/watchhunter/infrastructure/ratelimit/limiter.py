"""Thin facade around aiolimiter.AsyncLimiter for ergonomic use."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from aiolimiter import AsyncLimiter


class RateLimiter:
    """Rate limiter with EVEN pacing (no burst).

    Implemented as a single-token leaky bucket — one call is allowed every
    `60/rate_per_minute` seconds, then the next is blocked until that
    interval elapses. Critical for free-tier APIs that enforce a hard rolling
    window: a token-bucket limiter would allow N calls in the first 100ms
    and immediately blow the per-minute cap.

    Example:
        limiter = RateLimiter(rate_per_minute=6)   # 1 call every 10 seconds
        async with limiter:
            await call_api()
    """

    def __init__(self, *, rate_per_minute: int) -> None:
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be > 0")
        period = 60.0 / rate_per_minute
        # AsyncLimiter(max_rate, time_period_seconds): bucket size = max_rate.
        # max_rate=1 → no burst, smooth one-call-per-period pacing.
        self._limiter = AsyncLimiter(1, period)

    async def __aenter__(self) -> Self:
        await self._limiter.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None
