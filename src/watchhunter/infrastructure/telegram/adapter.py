"""NotifierPort backed by Telegram Bot API: one Russian card per find."""

from __future__ import annotations

import html
import re
from zoneinfo import ZoneInfo

from watchhunter.application.ports.notifier import (
    NotificationPayload,
    NotifierPort,
)
from watchhunter.config.logging import get_logger
from watchhunter.domain.exceptions import NotifierError
from watchhunter.infrastructure.telegram.client import TelegramBotClient
from watchhunter.infrastructure.telegram.formatting import card_keyboard, format_card

log = get_logger(__name__)


class TelegramNotifierAdapter(NotifierPort):
    def __init__(self, *, client: TelegramBotClient, timezone: str = "Europe/Berlin") -> None:
        self._client = client
        self._tz = ZoneInfo(timezone)

    async def send(self, payload: NotificationPayload) -> None:
        caption = format_card(payload, tz=self._tz)
        photo = str(payload.listing.image_urls[0]) if payload.listing.image_urls else None
        keyboard = card_keyboard(payload)
        if photo:
            try:
                await self._client.send_photo(photo_url=photo, caption=caption, keyboard=keyboard)
                return
            except NotifierError as exc:
                # Telegram could not fetch the image (or rejected the HTML).
                log.warning("telegram.photo_failed", error=str(exc)[:200])
        try:
            await self._client.send_message(text=caption, keyboard=keyboard)
            return
        except NotifierError as exc:
            log.warning("telegram.html_failed", error=str(exc)[:200])
        plain = html.unescape(re.sub(r"<[^>]+>", "", caption))
        await self._client.send_message(
            text=f"{plain}\n\n{payload.listing.url}", parse_mode="", keyboard=keyboard
        )
