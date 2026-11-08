"""NotifierPort backed by Telegram Bot API."""

from __future__ import annotations

import html

from watchhunter.application.ports.notifier import (
    NotificationPayload,
    NotifierPort,
)
from watchhunter.config.logging import get_logger
from watchhunter.domain.exceptions import NotifierError
from watchhunter.domain.models import BuyingOption
from watchhunter.infrastructure.telegram.client import TelegramBotClient

log = get_logger(__name__)

# Telegram limits:
#   sendPhoto caption  → 1024 chars
#   sendMessage text   → 4096 chars
#
# We aim for ~900 chars in the photo caption so HTML tags + escaping have safe
# overhead. When the full analysis would exceed this, we send a follow-up
# sendMessage with the untruncated reasoning + condition.
_CAPTION_BUDGET_CHARS = 900
_MAX_TITLE_CHARS = 110
_MAX_CONDITION_CHARS = 140
_MAX_REASONING_CHARS = 380


class TelegramNotifierAdapter(NotifierPort):
    def __init__(self, *, client: TelegramBotClient) -> None:
        self._client = client

    async def send(self, payload: NotificationPayload) -> None:
        caption_html = _format_caption_html(payload)
        photo = str(payload.listing.image_urls[0]) if payload.listing.image_urls else ""

        if photo:
            try:
                await self._client.send_photo(photo_url=photo, caption=caption_html)
                return
            except NotifierError as exc:
                log.warning("telegram.photo_failed", error=str(exc))

        plain = _format_caption_plain(payload)
        await self._client.send_message(text=plain, parse_mode="")


# ─── truncation helpers ──────────────────────────────────────────────────
def _truncate_sentence(s: str, n: int) -> str:
    """Truncate at a sentence boundary if possible; otherwise at a word."""
    s = s.strip()
    if len(s) <= n:
        return s
    window = s[: n + 1]
    # Look for a sentence-end punctuation in the latter half of the window.
    for end_char in (". ", "! ", "? ", ". \n", "! \n", "? \n"):
        idx = window.rfind(end_char)
        if idx > n * 0.55:
            return window[: idx + 1].rstrip()
    # Fall back to a word boundary.
    word_cut = window.rsplit(" ", 1)[0].rstrip(",;:—-")
    return word_cut + "…"


# ─── caption (photo + caption, max 1024) ─────────────────────────────────
def _format_caption_html(payload: NotificationPayload) -> str:
    listing = payload.listing
    ev = payload.evaluation
    is_bin = listing.buying_option == BuyingOption.FIXED_PRICE

    title = html.escape(_truncate_sentence(listing.title, _MAX_TITLE_CHARS))
    brand = html.escape(ev.brand)
    model = html.escape(ev.model)
    condition = html.escape(_truncate_sentence(ev.condition, _MAX_CONDITION_CHARS))
    reasoning = html.escape(_truncate_sentence(ev.reasoning, _MAX_REASONING_CHARS))

    badge = "🛒 <b>BUY NOW</b>" if is_bin else "🔨 <b>AUCTION</b>"
    rec_badge = _rec_badge_html(ev.recommendation.value)
    link_text = "🔗 Buy on eBay →" if is_bin else "🔗 View auction →"

    profit_pct = (
        (ev.potential_profit_eur / ev.current_price_eur * 100)
        if ev.current_price_eur > 0
        else 0
    )
    profit_sign = "+" if ev.potential_profit_eur >= 0 else ""

    # Auction-only fields
    bids_ends = ""
    if not is_bin:
        end_str = listing.end_time.strftime("%Y-%m-%d %H:%M UTC")
        bids_ends = f"🏷 {listing.bid_count} bids  ·  ⏰ {end_str}\n"

    # Optional shipping line — only show if we parsed a real value.
    shipping_line = _format_shipping_line(listing.shipping_cost_eur)

    return (
        f"{badge}  ·  {rec_badge}\n\n"
        f"<b>{title}</b>\n"
        f"<i>{brand} {model}</i>\n\n"
        f"💰 <b>€{listing.current_price_eur:.2f}</b> → "
        f"📈 <b>€{ev.estimated_market_value_eur:.2f}</b>  "
        f"<b>{profit_sign}{profit_pct:.0f}%</b>\n"
        f"🤑 Profit: <b>€{ev.potential_profit_eur:.2f}</b>\n"
        f"{shipping_line}"
        f"{bids_ends}"
        f"\n"
        f"⭐ <b>{ev.score}</b>/100  ·  Confidence <b>{ev.confidence}%</b>\n"
        f"🎯 Rarity <b>{ev.rarity.value}</b>  ·  Fake risk <b>{ev.fake_risk.value}</b>\n"
        f"\n"
        f"<blockquote expandable>"
        f"<b>Condition:</b> {condition}\n\n"
        f"<b>Analysis:</b> {reasoning}"
        f"</blockquote>\n"
        f'<a href="{listing.url}">{link_text}</a>'
    )


def _format_shipping_line(cost_eur) -> str:  # type: ignore[no-untyped-def]
    if cost_eur is None:
        return ""
    if cost_eur == 0:
        return "🚚 Shipping: <b>free</b>\n"
    return f"🚚 Shipping: <b>€{cost_eur:.2f}</b>\n"


def _rec_badge_html(recommendation: str) -> str:
    label = recommendation.upper()
    emoji = {"buy": "✅", "watch": "👀", "skip": "🚫"}.get(recommendation, "•")
    return f"{emoji} <b>{label}</b>"


# ─── plain-text fallback (when sendPhoto fails) ──────────────────────────
def _format_caption_plain(payload: NotificationPayload) -> str:
    listing = payload.listing
    ev = payload.evaluation
    is_bin = listing.buying_option == BuyingOption.FIXED_PRICE

    title = _truncate_sentence(listing.title, _MAX_TITLE_CHARS)
    condition = _truncate_sentence(ev.condition, _MAX_CONDITION_CHARS)
    reasoning = _truncate_sentence(ev.reasoning, _MAX_REASONING_CHARS)
    badge = "BUY NOW" if is_bin else "AUCTION"
    profit_pct = (
        (ev.potential_profit_eur / ev.current_price_eur * 100)
        if ev.current_price_eur > 0
        else 0
    )

    bids_ends = ""
    if not is_bin:
        end_str = listing.end_time.strftime("%Y-%m-%d %H:%M UTC")
        bids_ends = f"{listing.bid_count} bids · Ends {end_str}\n"

    shipping = ""
    if listing.shipping_cost_eur is not None:
        shipping = (
            "Shipping: free\n"
            if listing.shipping_cost_eur == 0
            else f"Shipping: €{listing.shipping_cost_eur:.2f}\n"
        )

    return (
        f"[{badge}] {ev.recommendation.value.upper()}\n"
        f"{title}\n"
        f"{ev.brand} {ev.model}\n\n"
        f"€{listing.current_price_eur:.2f} → €{ev.estimated_market_value_eur:.2f} "
        f"(+{profit_pct:.0f}%)\n"
        f"Profit: €{ev.potential_profit_eur:.2f}\n"
        f"{shipping}"
        f"{bids_ends}\n"
        f"Score {ev.score}/100 · Confidence {ev.confidence}%\n"
        f"Rarity {ev.rarity.value} · Fake risk {ev.fake_risk.value}\n\n"
        f"Condition: {condition}\n\n"
        f"Analysis: {reasoning}\n\n"
        f"{listing.url}"
    )
