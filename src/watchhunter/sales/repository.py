"""Sale history storage: track evaluated auctions, snapshot them, read stats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median

from sqlalchemy import select

from watchhunter.domain.evaluation import WatchEvaluation
from watchhunter.domain.models import BuyingOption, Listing
from watchhunter.domain.reference import reference_key
from watchhunter.infrastructure.persistence.database import Database
from watchhunter.infrastructure.persistence.models import SaleRow


@dataclass(frozen=True)
class SaleStats:
    ref_key: str
    sold: int  # auctions that ended with bids
    unsold: int  # ended without bids
    low: Decimal | None
    median: Decimal | None
    high: Decimal | None
    days: int


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class SalesRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def track(self, listing: Listing, ev: WatchEvaluation) -> None:
        """Start following an evaluated auction until it ends (idempotent)."""
        if listing.buying_option != BuyingOption.AUCTION:
            return
        key = reference_key(ev.brand, ev.model)
        if not key:
            return
        async with self._db.session() as s:
            row = await s.scalar(select(SaleRow).where(SaleRow.external_id == listing.external_id))
            if row is not None:
                return
            s.add(
                SaleRow(
                    external_id=listing.external_id,
                    marketplace=listing.marketplace.value,
                    ref_key=key,
                    brand=ev.brand,
                    model=ev.model,
                    title=listing.title[:500],
                    url=str(listing.url),
                    end_time=listing.end_time,
                    estimate_eur=ev.estimated_market_value_eur,
                    last_price_eur=listing.current_price_eur,
                    bid_count=listing.bid_count,
                    snapshot_at=datetime.now(timezone.utc),
                )
            )

    async def ended(self, *, grace: timedelta) -> list[SaleRow]:
        """Tracked auctions that ended at least `grace` ago and aren't closed yet."""
        cutoff = datetime.now(timezone.utc) - grace
        async with self._db.session() as s:
            rows = await s.scalars(
                select(SaleRow).where(SaleRow.final.is_(False)).where(SaleRow.end_time <= cutoff)
            )
            return list(rows)

    async def snapshot(self, sale_id: int, price: Decimal | None, bids: int | None) -> None:
        async with self._db.session() as s:
            row = await s.get(SaleRow, sale_id)
            if row is None:
                return
            if price is not None:
                row.last_price_eur = price
            if bids is not None:
                row.bid_count = bids
            row.snapshot_at = datetime.now(timezone.utc)

    async def finalize(self, sale_id: int) -> bool:
        """Close the record; True when the auction sold (ended with bids)."""
        async with self._db.session() as s:
            row = await s.get(SaleRow, sale_id)
            if row is None:
                return False
            row.final = True
            row.sold = row.bid_count > 0
            return row.sold

    async def stats(self, ref_key: str, days: int = 90) -> SaleStats | None:
        if not ref_key:
            return None
        since = datetime.now(timezone.utc) - timedelta(days=days)
        async with self._db.session() as s:
            rows = list(
                await s.scalars(
                    select(SaleRow)
                    .where(SaleRow.ref_key == ref_key)
                    .where(SaleRow.final.is_(True))
                    .where(SaleRow.end_time >= since)
                )
            )
        if not rows:
            return None
        prices = sorted(r.last_price_eur for r in rows if r.sold and r.last_price_eur is not None)
        return SaleStats(
            ref_key=ref_key,
            sold=len(prices),
            unsold=sum(1 for r in rows if not r.sold),
            low=prices[0] if prices else None,
            median=Decimal(str(median(prices))) if prices else None,
            high=prices[-1] if prices else None,
            days=days,
        )

    async def accuracy(self, days: int = 30) -> tuple[int, Decimal | None]:
        """(n, median absolute % error of our estimate vs the final price)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        async with self._db.session() as s:
            rows = list(
                await s.scalars(
                    select(SaleRow)
                    .where(SaleRow.final.is_(True), SaleRow.sold.is_(True))
                    .where(SaleRow.end_time >= since)
                )
            )
        errs = [
            abs(r.estimate_eur - r.last_price_eur) / r.last_price_eur * 100
            for r in rows
            if r.estimate_eur and r.last_price_eur and r.last_price_eur > 0
        ]
        return len(errs), (Decimal(str(median(errs))).quantize(Decimal("1")) if errs else None)

    async def overestimate(self, days: int = 30, min_n: int = 10) -> tuple[int, float] | None:
        """(n, median of estimate / final price) over recent sold auctions."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        async with self._db.session() as s:
            rows = list(
                await s.scalars(
                    select(SaleRow)
                    .where(SaleRow.final.is_(True), SaleRow.sold.is_(True))
                    .where(SaleRow.end_time >= since)
                )
            )
        ratios = [
            float(r.estimate_eur / r.last_price_eur)
            for r in rows
            if r.estimate_eur and r.last_price_eur and r.last_price_eur > 0
        ]
        if len(ratios) < min_n:
            return None
        return len(ratios), float(median(ratios))
