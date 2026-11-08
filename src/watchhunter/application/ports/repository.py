"""Port for persisting listings + evaluations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from watchhunter.domain.evaluation import WatchEvaluation
from watchhunter.domain.models import Listing


@dataclass(frozen=True)
class StoredListing:
    """A listing + its latest evaluation, as returned by the repository."""

    listing: Listing
    evaluation: WatchEvaluation
    listing_id: int
    evaluation_id: int
    notified_at: datetime | None


class ListingRepository(ABC):
    @abstractmethod
    async def upsert_listing(self, listing: Listing) -> int:
        """Insert or update a listing. Returns the internal row ID."""

    @abstractmethod
    async def save_evaluation(
        self,
        listing_id: int,
        evaluation: WatchEvaluation,
    ) -> int:
        """Persist an evaluation linked to the given listing. Returns evaluation row ID."""

    @abstractmethod
    async def get_recent_evaluation(
        self,
        external_id: str,
        within_hours: int,
    ) -> WatchEvaluation | None:
        """Return the most recent evaluation for this external_id, if newer than `within_hours`."""

    @abstractmethod
    async def was_ever_notified(self, external_id: str) -> bool:
        """True if any evaluation for this listing has already been delivered.

        Used to suppress duplicate notifications across restarts.
        """

    @abstractmethod
    async def was_ever_seen(self, external_id: str) -> bool:
        """True if a row for this external_id exists in the listings table.

        Used by 'fresh-only' Buy-It-Now scans: once we've ever seen and
        analyzed a fixed-price listing, we never re-analyze it — if it's
        still up, it wasn't a bargain.
        """

    @abstractmethod
    async def list_unnotified_promising(
        self,
        min_score: int,
        limit: int = 50,
    ) -> list[StoredListing]:
        """List stored promising listings that have not been notified yet."""

    @abstractmethod
    async def mark_notified(self, evaluation_id: int) -> None:
        """Mark an evaluation as notified at the current time."""
