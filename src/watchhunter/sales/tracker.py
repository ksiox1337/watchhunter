"""Read each tracked auction once it has ended: the final price and bid count.

The Browse API still returns an ended auction (status OUT_OF_STOCK) with its
final currentBidPrice and bidCount, so this is the real hammer price.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from watchhunter.application.ports.marketplace import MarketplacePort
from watchhunter.config.logging import get_logger
from watchhunter.domain.models import Listing, Marketplace
from watchhunter.sales.repository import SalesRepository, _utc

log = get_logger(__name__)


class SalesTracker:
    def __init__(
        self,
        *,
        repository: SalesRepository,
        marketplace: MarketplacePort,
        grace: timedelta = timedelta(minutes=2),
    ) -> None:
        self._repo = repository
        self._market = marketplace
        self._grace = grace

    async def execute(self) -> dict[str, int]:
        stats = {"sold": 0, "unsold": 0, "errors": 0}
        for row in await self._repo.ended(grace=self._grace):
            stub = Listing(
                external_id=row.external_id,
                marketplace=Marketplace(row.marketplace),
                title=row.title or "-",
                url=row.url,  # type: ignore[arg-type]
                current_price=row.last_price_eur or Decimal("0"),
                currency="EUR",
                current_price_eur=row.last_price_eur or Decimal("0"),
                bid_count=row.bid_count,
                end_time=_utc(row.end_time),
            )
            try:
                state = await self._market.refresh_state(stub)
                await self._repo.snapshot(row.id, state.price_eur, state.bid_count)
            except Exception as exc:
                log.warning("sales.read_failed", external_id=row.external_id, error=str(exc)[:160])
                stats["errors"] += 1
            sold = await self._repo.finalize(row.id)
            stats["sold" if sold else "unsold"] += 1
        if any(stats.values()):
            log.info("sales.tick", **stats)
        return stats
