"""Periodic notification job — backstop sweep over the DB.

Most notifications go out push-style from the scan use case as soon as a
listing is saved. This job catches anything that the push path missed
(e.g. notifier was down) and runs much less frequently.
"""

from __future__ import annotations

import asyncio

from watchhunter.application.ports.repository import ListingRepository
from watchhunter.application.services.promising_notifier import PromisingNotifier
from watchhunter.config.logging import get_logger

log = get_logger(__name__)


class NotifyPromisingUseCase:
    def __init__(
        self,
        *,
        repository: ListingRepository,
        promising_notifier: PromisingNotifier,
        min_score: int,
        batch_size: int = 25,
        delay_between_messages_s: float = 1.5,
    ) -> None:
        self._repo = repository
        self._notifier = promising_notifier
        self._min_score = min_score
        self._batch_size = batch_size
        self._delay = delay_between_messages_s

    async def execute(self) -> dict[str, int]:
        stats = {
            "sent": 0,
            "skipped_overpriced": 0,
            "skipped_shipping": 0,
            "skipped_gone": 0,
            "errors": 0,
        }
        items = await self._repo.list_unnotified_promising(
            self._min_score, limit=self._batch_size
        )
        log.info("notify.batch_loaded", count=len(items))

        for stored in items:
            outcome = await self._notifier.notify_one(
                stored.listing, stored.evaluation, stored.evaluation_id
            )
            if outcome == "sent":
                stats["sent"] += 1
            elif outcome == "overpriced":
                stats["skipped_overpriced"] += 1
            elif outcome == "shipping":
                stats["skipped_shipping"] += 1
            elif outcome == "gone":
                stats["skipped_gone"] += 1
            else:
                stats["errors"] += 1
            await asyncio.sleep(self._delay)

        log.info("notify.complete", **stats)
        return stats
