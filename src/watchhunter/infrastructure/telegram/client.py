"""Minimal async Telegram Bot API client."""

from __future__ import annotations

from typing import Any

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from watchhunter.config.logging import get_logger
from watchhunter.domain.exceptions import NotifierError
from watchhunter.infrastructure.http.client import HttpClient

log = get_logger(__name__)


class TelegramBotClient:
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        http: HttpClient,
    ) -> None:
        if not bot_token or not chat_id:
            raise NotifierError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._http = http
        self._base = f"https://api.telegram.org/bot{bot_token}"

    async def send_photo(
        self,
        *,
        photo_url: str,
        caption: str,
        parse_mode: str = "HTML",
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": parse_mode,
        }
        await self._post("/sendPhoto", payload)

    async def send_message(
        self,
        *,
        text: str,
        parse_mode: str = "HTML",
        preview_url: str | None = None,
        button: tuple[str, str] | None = None,
    ) -> None:
        """Send text. `preview_url` shows that image as a large preview above
        the text; `button` is an inline (label, url) button under the message."""
        payload: dict[str, Any] = {"chat_id": self._chat_id, "text": text[:4096]}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if preview_url:
            payload["link_preview_options"] = {
                "url": preview_url,
                "prefer_large_media": True,
                "show_above_text": True,
            }
        else:
            payload["link_preview_options"] = {"is_disabled": True}
        if button:
            payload["reply_markup"] = {
                "inline_keyboard": [[{"text": button[0], "url": button[1]}]]
            }
        await self._post("/sendMessage", payload)

    async def _post(self, path: str, payload: dict[str, Any]) -> None:
        url = f"{self._base}{path}"
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(min=1, max=10),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                async with self._http.session.post(url, json=payload) as resp:
                    body = await resp.json(content_type=None)
                    if resp.status >= 400 or not body.get("ok", False):
                        # If photo failed (e.g. eBay blocks Telegram), fall through with a clear error.
                        raise NotifierError(
                            f"Telegram {path} failed (status {resp.status}): "
                            f"{body.get('description', body)}"
                        )
