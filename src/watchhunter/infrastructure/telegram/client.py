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
        keyboard: list[list[dict[str, str]]] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "photo": photo_url,
            "caption": caption[:1024],
            "parse_mode": parse_mode,
        }
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        await self._post("/sendPhoto", payload)

    async def send_message(
        self,
        *,
        text: str,
        parse_mode: str = "HTML",
        preview_url: str | None = None,
        keyboard: list[list[dict[str, str]]] | None = None,
    ) -> None:
        """Send text. `preview_url` shows that image as a large preview above
        the text; `keyboard` is an inline keyboard (rows of buttons) under it."""
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
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        await self._post("/sendMessage", payload)

    # ─── receiving: buttons and commands ─────────────────────────────────
    @property
    def chat_id(self) -> str:
        return self._chat_id

    async def get_updates(self, offset: int) -> list[dict[str, Any]]:
        body = await self._post(
            "/getUpdates",
            {"offset": offset, "timeout": 0, "allowed_updates": ["message", "callback_query"]},
        )
        return list(body.get("result") or [])

    async def answer_callback(self, callback_id: str, text: str) -> None:
        await self._post("/answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    async def edit_keyboard(
        self, *, chat_id: str | int, message_id: int, keyboard: list[list[dict[str, str]]]
    ) -> None:
        await self._post(
            "/editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": keyboard}},
        )

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
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
                    return body  # type: ignore[no-any-return]
        return {}
