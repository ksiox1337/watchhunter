"""Handle what you send back: feedback buttons under cards and /stats."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from watchhunter.config.logging import get_logger
from watchhunter.infrastructure.persistence.database import Database
from watchhunter.infrastructure.persistence.models import (
    EvaluationRow,
    FeedbackRow,
    GeminiUsageRow,
    SaleRow,
)
from watchhunter.infrastructure.telegram.client import TelegramBotClient
from watchhunter.infrastructure.telegram.formatting import FEEDBACK, feedback_row

log = get_logger(__name__)


class TelegramUpdates:
    def __init__(self, *, client: TelegramBotClient, database: Database) -> None:
        self._client = client
        self._db = database
        self._offset = 0

    async def execute(self) -> None:
        for upd in await self._client.get_updates(self._offset):
            self._offset = max(self._offset, int(upd["update_id"]) + 1)
            try:
                if "callback_query" in upd:
                    await self._on_button(upd["callback_query"])
                elif "message" in upd:
                    await self._on_message(upd["message"])
            except Exception as exc:
                log.warning("telegram.update_failed", error=str(exc)[:160])

    def _ours(self, chat: dict) -> bool:  # type: ignore[type-arg]
        return str(chat.get("id")) == str(self._client.chat_id)

    async def _on_button(self, cq: dict) -> None:  # type: ignore[type-arg]
        msg = cq.get("message") or {}
        if not self._ours(msg.get("chat") or {}):
            return
        kind, ev_id, action = (str(cq.get("data") or "") + "::").split(":")[:3]
        if kind != "fb" or action not in FEEDBACK:
            return
        async with self._db.session() as s:
            s.add(FeedbackRow(evaluation_id=int(ev_id), action=action, created_at=datetime.now(timezone.utc)))
        await self._client.answer_callback(cq["id"], f"Saved {FEEDBACK[action]}")
        rows = (msg.get("reply_markup") or {}).get("inline_keyboard") or []
        rows = [r for r in rows if not any(str(b.get("callback_data", "")).startswith("fb:") for b in r)]
        rows.append(feedback_row(int(ev_id), action))
        await self._client.edit_keyboard(
            chat_id=msg["chat"]["id"], message_id=msg["message_id"], keyboard=rows
        )
        log.info("feedback.saved", evaluation_id=ev_id, action=action)

    async def _on_message(self, msg: dict) -> None:  # type: ignore[type-arg]
        if not self._ours(msg.get("chat") or {}):
            return
        if (msg.get("text") or "").strip().split("@")[0] in ("/stats", "/start"):
            await self._client.send_message(text=await self._stats_text())

    async def _stats_text(self) -> str:
        day = datetime.now(timezone.utc) - timedelta(hours=24)
        async with self._db.session() as s:
            evals = await s.scalar(select(func.count(EvaluationRow.id)).where(EvaluationRow.created_at >= day))
            sent = await s.scalar(select(func.count(EvaluationRow.id)).where(EvaluationRow.notified_at >= day))
            cost = await s.scalar(select(func.coalesce(func.sum(GeminiUsageRow.cost_usd), 0)).where(GeminiUsageRow.created_at >= day))
            tracked = await s.scalar(select(func.count(SaleRow.id)))
            closed = await s.scalar(select(func.count(SaleRow.id)).where(SaleRow.final.is_(True), SaleRow.sold.is_(True)))
            fb = dict(
                (await s.execute(select(FeedbackRow.action, func.count(FeedbackRow.id)).group_by(FeedbackRow.action))).all()
            )
        fb_line = " ".join(f"{FEEDBACK[a]} {fb.get(a, 0)}" for a in FEEDBACK)
        return (
            "<b>WatchHunter · last 24 h</b>\n"
            f"Evaluated from photos: {evals}\n"
            f"Finds sent: {sent}\n"
            f"Model spend: ${float(cost):.3f}\n\n"
            f"<b>Sales history</b>\nAuctions tracked: {tracked}, sales closed: {closed}\n\n"
            f"<b>Your ratings</b>: {fb_line}"
        )
