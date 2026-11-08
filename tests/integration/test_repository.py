"""Integration test for SqlAlchemyListingRepository against an in-memory SQLite."""

from __future__ import annotations

import pytest

from watchhunter.domain.evaluation import WatchEvaluation
from watchhunter.domain.models import Listing
from watchhunter.infrastructure.persistence.database import Database
from watchhunter.infrastructure.persistence.repository import (
    SqlAlchemyListingRepository,
)


@pytest.fixture
async def repo() -> SqlAlchemyListingRepository:
    db = Database(url="sqlite+aiosqlite:///:memory:")
    await db.init()
    return SqlAlchemyListingRepository(db)


async def test_upsert_and_evaluate(
    repo: SqlAlchemyListingRepository,
    sample_listing: Listing,
    sample_evaluation: WatchEvaluation,
) -> None:
    listing_id = await repo.upsert_listing(sample_listing)
    assert listing_id > 0

    # Idempotent upsert
    same_id = await repo.upsert_listing(sample_listing)
    assert same_id == listing_id

    eval_id = await repo.save_evaluation(listing_id, sample_evaluation)
    assert eval_id > 0

    recent = await repo.get_recent_evaluation(sample_listing.external_id, within_hours=1)
    assert recent is not None
    assert recent.brand == sample_evaluation.brand


async def test_list_unnotified_and_mark(
    repo: SqlAlchemyListingRepository,
    sample_listing: Listing,
    sample_evaluation: WatchEvaluation,
) -> None:
    listing_id = await repo.upsert_listing(sample_listing)
    eval_id = await repo.save_evaluation(listing_id, sample_evaluation)

    pending = await repo.list_unnotified_promising(min_score=60)
    assert len(pending) == 1
    assert pending[0].evaluation_id == eval_id

    await repo.mark_notified(eval_id)
    pending_after = await repo.list_unnotified_promising(min_score=60)
    assert pending_after == []
