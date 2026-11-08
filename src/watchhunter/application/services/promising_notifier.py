"""Reusable 'verify state + notify' service.

Used by:
  • ScanWatchesUseCase  → push-on-save: notify immediately after analysis.
  • NotifyPromisingUseCase → periodic backstop sweep over the DB.

Encapsulates: re-fetch current price + shipping from the item page, skip if
over either budget or gone, update the listing snapshot, send to the notifier,
mark the evaluation as notified.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from watchhunter.application.ports.marketplace import MarketplacePort
from watchhunter.application.ports.notifier import (
    NotificationPayload,
    NotifierPort,
)
from watchhunter.application.ports.repository import ListingRepository
from watchhunter.config.logging import get_logger
from watchhunter.domain.evaluation import WatchEvaluation
from watchhunter.domain.exceptions import NotifierError
from watchhunter.domain.models import BuyingOption, Listing

log = get_logger(__name__)

NotifyOutcome = Literal["sent", "overpriced", "shipping", "gone", "error"]


class PromisingNotifier:
    def __init__(
        self,
        *,
        notifier: NotifierPort,
        marketplace: MarketplacePort,
        repository: ListingRepository,
        max_price_eur: Decimal | None = None,
        max_shipping_eur: Decimal | None = None,
    ) -> None:
        self._notifier = notifier
        self._marketplace = marketplace
        self._repo = repository
        self._max_price_eur = max_price_eur
        self._max_shipping_eur = max_shipping_eur

    async def notify_one(
        self,
        listing: Listing,
        evaluation: WatchEvaluation,
        evaluation_id: int,
    ) -> NotifyOutcome:
        # An auction that has already ended is never worth a message.
        if (
            listing.buying_option == BuyingOption.AUCTION
            and listing.end_time <= datetime.now(timezone.utc)
        ):
            log.info("notify.listing_ended", external_id=listing.external_id)
            return "gone"
        needs_refresh = (
            self._max_price_eur is not None or self._max_shipping_eur is not None
        )

        if needs_refresh:
            try:
                state = await self._marketplace.refresh_state(listing)
            except Exception as exc:
                log.warning(
                    "notify.refresh_failed",
                    external_id=listing.external_id,
                    error=str(exc),
                )
                state = None
        else:
            state = None

        if state is not None:
            if state.price_eur is None:
                log.info("notify.listing_gone", external_id=listing.external_id)
                await self._repo.mark_notified(evaluation_id)
                return "gone"

            if (
                self._max_price_eur is not None
                and state.price_eur > self._max_price_eur
            ):
                log.info(
                    "notify.skipped_overpriced",
                    external_id=listing.external_id,
                    current_eur=str(state.price_eur),
                    cap_eur=str(self._max_price_eur),
                )
                await self._repo.mark_notified(evaluation_id)
                return "overpriced"

            if (
                self._max_shipping_eur is not None
                and state.shipping_eur is not None
                and state.shipping_eur > self._max_shipping_eur
            ):
                log.info(
                    "notify.skipped_shipping",
                    external_id=listing.external_id,
                    shipping_eur=str(state.shipping_eur),
                    cap_eur=str(self._max_shipping_eur),
                )
                await self._repo.mark_notified(evaluation_id)
                return "shipping"

            # Update listing snapshot for accurate caption.
            updates = {}
            if state.price_eur != listing.current_price_eur:
                updates["current_price_eur"] = state.price_eur
            if (
                state.shipping_eur is not None
                and state.shipping_eur != listing.shipping_cost_eur
            ):
                updates["shipping_cost_eur"] = state.shipping_eur
            if updates:
                listing = listing.model_copy(update=updates)

        payload = NotificationPayload(
            listing=listing, evaluation=evaluation, evaluation_id=evaluation_id
        )
        try:
            await self._notifier.send(payload)
            await self._repo.mark_notified(evaluation_id)
            return "sent"
        except NotifierError as exc:
            log.warning(
                "notify.error",
                evaluation_id=evaluation_id,
                error=str(exc),
            )
            return "error"
