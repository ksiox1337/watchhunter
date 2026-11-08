"""SQLAlchemy ORM models — physical schema."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ListingRow(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ebay_item_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    marketplace: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1024))
    current_price_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    original_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    original_currency: Mapped[str] = mapped_column(String(3))
    bid_count: Mapped[int] = mapped_column(Integer, default=0)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    image_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    evaluations: Mapped[list[EvaluationRow]] = relationship(
        back_populates="listing",
        cascade="all, delete-orphan",
        order_by="EvaluationRow.created_at.desc()",
    )


class EvaluationRow(Base):
    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )

    interesting: Mapped[bool] = mapped_column(default=False)
    score: Mapped[int] = mapped_column(Integer, index=True)
    brand: Mapped[str] = mapped_column(String(128), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    estimated_market_value_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    current_price_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    potential_profit_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    rarity: Mapped[str] = mapped_column(String(16))
    condition: Mapped[str] = mapped_column(String(64))
    fake_risk: Mapped[str] = mapped_column(String(16))
    recommendation: Mapped[str] = mapped_column(String(16), index=True)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    raw_response: Mapped[dict] = mapped_column(JSON, default=dict)  # type: ignore[type-arg]

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )

    listing: Mapped[ListingRow] = relationship(back_populates="evaluations")


Index("ix_eval_score_notified", EvaluationRow.score.desc(), EvaluationRow.notified_at)


class GeminiUsageRow(Base):
    """One row per Gemini API call. Aggregated for daily cost / budget cap."""

    __tablename__ = "gemini_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(String(64), index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


Index("ix_usage_day_model", GeminiUsageRow.created_at, GeminiUsageRow.model)


class SaleRow(Base):
    """Our own sale history: auctions we evaluated, snapshotted until they end.

    The last snapshot before the end is close to the hammer price. Unsold
    auctions (0 bids at the end) are kept with sold=False.
    """

    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    marketplace: Mapped[str] = mapped_column(String(32))
    ref_key: Mapped[str] = mapped_column(String(64), index=True)
    brand: Mapped[str] = mapped_column(String(128), default="")
    model: Mapped[str] = mapped_column(String(256), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    url: Mapped[str] = mapped_column(String(1024), default="")
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    estimate_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    last_price_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    bid_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sold: Mapped[bool] = mapped_column(Boolean, default=False)


class ImageHashRow(Base):
    """Perceptual hash of a listing's first photo, to spot reused photos."""

    __tablename__ = "image_hashes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    url: Mapped[str] = mapped_column(String(1024))
    listing_url: Mapped[str] = mapped_column(String(1024), default="")
    phash: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FeedbackRow(Base):
    """Your reaction to a sent card (Telegram buttons)."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluation_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(16))  # like | dislike | bought
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
