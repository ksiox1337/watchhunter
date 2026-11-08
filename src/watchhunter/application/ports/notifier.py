"""Port for any notification channel (Telegram, Slack, …)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from watchhunter.domain.evaluation import WatchEvaluation
from watchhunter.domain.models import Listing


@dataclass(frozen=True)
class NotificationPayload:
    listing: Listing
    evaluation: WatchEvaluation
    evaluation_id: int | None = None  # lets the card carry feedback buttons


class NotifierPort(ABC):
    @abstractmethod
    async def send(self, payload: NotificationPayload) -> None:
        raise NotImplementedError
