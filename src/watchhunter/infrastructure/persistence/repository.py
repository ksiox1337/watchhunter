"""Concrete SQLAlchemy implementation of ListingRepository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy.orm import selectinload

from watchhunter.application.ports.repository import ListingRepository, StoredListing
from watchhunter.domain.evaluation import (
    FakeRisk,
    RarityLevel,
    Recommendation,
    WatchEvaluation,
)
from watchhunter.domain.models import Listing, Marketplace
from watchhunter.infrastructure.persistence.database import Database
from watchhunter.infrastructure.persistence.models import EvaluationRow, ListingRow


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    """SQLite via aiosqlite returns naive datetimes; assume they're UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _row_to_listing(row: ListingRow) -> Listing:
    return Listing(
        external_id=row.ebay_item_id,
        marketplace=Marketplace(row.marketplace),
        title=row.title,
        description=row.description,
        url=row.url,  # type: ignore[arg-type]
        current_price=row.original_price,
        currency=row.original_currency,
        current_price_eur=row.current_price_eur,
        bid_count=row.bid_count,
        end_time=_ensure_utc(row.end_time),
        image_urls=tuple(row.image_urls or ()),  # type: ignore[arg-type]
    )


def _row_to_eval(row: EvaluationRow) -> WatchEvaluation:
    return WatchEvaluation(
        interesting=row.interesting,
        score=row.score,
        brand=row.brand,
        model=row.model,
        confidence=row.confidence,
        estimated_market_value_eur=row.estimated_market_value_eur,
        current_price_eur=row.current_price_eur,
        potential_profit_eur=row.potential_profit_eur,
        rarity=RarityLevel(row.rarity),
        condition=row.condition,
        fake_risk=FakeRisk(row.fake_risk),
        recommendation=Recommendation(row.recommendation),
        reasoning=row.reasoning,
        raw_response=row.raw_response or {},
    )


class SqlAlchemyListingRepository(ListingRepository):
    def __init__(self, database: Database) -> None:
        self._db = database
        self._sessionmaker: async_sessionmaker[AsyncSession] = database.sessionmaker

    async def upsert_listing(self, listing: Listing) -> int:
        async with self._db.session() as session:
            row = await session.scalar(
                select(ListingRow).where(ListingRow.ebay_item_id == listing.external_id)
            )
            now = _utcnow()
            if row is None:
                row = ListingRow(
                    ebay_item_id=listing.external_id,
                    marketplace=listing.marketplace.value,
                    title=listing.title,
                    description=listing.description,
                    url=str(listing.url),
                    current_price_eur=listing.current_price_eur,
                    original_price=listing.current_price,
                    original_currency=listing.currency,
                    bid_count=listing.bid_count,
                    end_time=listing.end_time,
                    image_urls=[str(u) for u in listing.image_urls],
                    first_seen_at=now,
                    last_seen_at=now,
                )
                session.add(row)
            else:
                row.title = listing.title
                row.description = listing.description
                row.current_price_eur = listing.current_price_eur
                row.original_price = listing.current_price
                row.original_currency = listing.currency
                row.bid_count = listing.bid_count
                row.end_time = listing.end_time
                row.image_urls = [str(u) for u in listing.image_urls]
                row.last_seen_at = now
            await session.flush()
            return row.id

    async def save_evaluation(
        self, listing_id: int, evaluation: WatchEvaluation
    ) -> int:
        async with self._db.session() as session:
            row = EvaluationRow(
                listing_id=listing_id,
                interesting=evaluation.interesting,
                score=evaluation.score,
                brand=evaluation.brand,
                model=evaluation.model,
                confidence=evaluation.confidence,
                estimated_market_value_eur=evaluation.estimated_market_value_eur,
                current_price_eur=evaluation.current_price_eur,
                potential_profit_eur=evaluation.potential_profit_eur,
                rarity=evaluation.rarity.value,
                condition=evaluation.condition,
                fake_risk=evaluation.fake_risk.value,
                recommendation=evaluation.recommendation.value,
                reasoning=evaluation.reasoning,
                raw_response=evaluation.raw_response,
                created_at=_utcnow(),
            )
            session.add(row)
            await session.flush()
            return row.id

    async def was_ever_seen(self, external_id: str) -> bool:
        async with self._db.session() as session:
            row = await session.scalar(
                select(ListingRow.id).where(ListingRow.ebay_item_id == external_id)
            )
            return row is not None

    async def was_ever_notified(self, external_id: str) -> bool:
        async with self._db.session() as session:
            row = await session.scalar(
                select(EvaluationRow.id)
                .join(ListingRow, ListingRow.id == EvaluationRow.listing_id)
                .where(ListingRow.ebay_item_id == external_id)
                .where(EvaluationRow.notified_at.is_not(None))
                .limit(1)
            )
            return row is not None

    async def get_recent_evaluation(
        self, external_id: str, within_hours: int
    ) -> WatchEvaluation | None:
        cutoff = _utcnow() - timedelta(hours=within_hours)
        async with self._db.session() as session:
            row = await session.scalar(
                select(EvaluationRow)
                .join(ListingRow, ListingRow.id == EvaluationRow.listing_id)
                .where(ListingRow.ebay_item_id == external_id)
                .where(EvaluationRow.created_at >= cutoff)
                .order_by(EvaluationRow.created_at.desc())
                .limit(1)
            )
            return _row_to_eval(row) if row else None

    async def list_unnotified_promising(
        self, min_score: int, limit: int = 50
    ) -> list[StoredListing]:
        now = _utcnow()
        async with self._db.session() as session:
            rows = (
                await session.scalars(
                    select(EvaluationRow)
                    .options(selectinload(EvaluationRow.listing))
                    .where(EvaluationRow.score >= min_score)
                    .where(EvaluationRow.recommendation != Recommendation.SKIP.value)
                    .where(EvaluationRow.notified_at.is_(None))
                    .join(ListingRow, ListingRow.id == EvaluationRow.listing_id)
                    .where(ListingRow.end_time > now)
                    .order_by(EvaluationRow.score.desc(), EvaluationRow.created_at.desc())
                    .limit(limit)
                )
            ).all()
            return [
                StoredListing(
                    listing=_row_to_listing(r.listing),
                    evaluation=_row_to_eval(r),
                    listing_id=r.listing_id,
                    evaluation_id=r.id,
                    notified_at=_ensure_utc(r.notified_at) if r.notified_at else None,
                )
                for r in rows
            ]

    async def mark_notified(self, evaluation_id: int) -> None:
        async with self._db.session() as session:
            row = await session.get(EvaluationRow, evaluation_id)
            if row is not None:
                row.notified_at = _utcnow()


# Re-export decimal so type-checkers see it in the public surface
__all__ = ["SqlAlchemyListingRepository", "Decimal"]
