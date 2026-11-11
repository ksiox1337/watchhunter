"""Telegram card for one find: big photo, short caption of 4-5 lines,
reasons / story / checks in a collapsed quote, and an inline eBay button."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from watchhunter.application.ports.notifier import NotificationPayload
from watchhunter.domain.evaluation import FakeRisk, RarityLevel, Recommendation
from watchhunter.domain.models import BuyingOption, Marketplace

_VERDICT = {
    Recommendation.BUY: "🟢 <b>BUY</b>",
    Recommendation.WATCH: "🟡 <b>WATCH</b>",
    Recommendation.SKIP: "⚪️ <b>SKIP</b>",
}
_LEVEL = {"low": "low", "medium": "medium", "high": "high", "very_high": "grail"}
_RARITY = {
    "low": "⚪️ Rarity: common",
    "medium": "🔹 Rarity: uncommon",
    "high": "💎 Rarity: rare",
    "very_high": "💎💎 Rarity: grail",
}
_RISK = {"low": "low", "medium": "medium", "high": "high"}
_SOURCE = {
    Marketplace.KLEINANZEIGEN: "Kleinanzeigen",
}


def money(value: Decimal | None, *, sign: bool = False) -> str:
    """1234.5 → '1 234,50 €' (no decimals for round euros ≥ 100)."""
    if value is None:
        return "—"
    v = Decimal(value)
    if abs(v) >= 100:
        v = v.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        body = f"{abs(v):,.0f}"
    else:
        v = v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        body = f"{abs(v):,.2f}"
    prefix = ("+" if v > 0 else "−" if v < 0 else "") if sign else ("−" if v < 0 else "")
    return f"{prefix}€{body}"


def _time_left(end: datetime, now: datetime) -> str:
    minutes = int((end - now).total_seconds() // 60)
    if minutes <= 0:
        return "ended"
    h, m = divmod(minutes, 60)
    if h >= 48:
        return f"in {h // 24} d"
    return f"in {h} h {m} min" if h else f"in {m} min"


def _end_label(end: datetime, now: datetime, tz: ZoneInfo) -> str:
    local_end, local_now = end.astimezone(tz), now.astimezone(tz)
    days = (local_end.date() - local_now.date()).days
    day = {0: "today", 1: "tomorrow"}.get(days, local_end.strftime("%b %d"))
    return f"{day} {local_end:%H:%M} · {_time_left(end, now)}"


def _bullets(items: tuple[str, ...], limit: int) -> str:
    return "\n".join(f"• {html.escape(x.strip().rstrip('.'))}" for x in items[:limit])


CAPTION_LIMIT = 1024


def format_card(
    payload: NotificationPayload,
    *,
    tz: ZoneInfo,
    now: datetime | None = None,
    limit: int = CAPTION_LIMIT,
) -> str:
    """Photo caption: 4-5 short lines, details in a collapsed quote."""
    listing, ev = payload.listing, payload.evaluation
    now = now or datetime.now(timezone.utc)
    is_bin = listing.buying_option == BuyingOption.FIXED_PRICE

    kind = "Buy It Now" if is_bin else "Auction"
    head = f"{_VERDICT.get(ev.recommendation, '')} · {kind} · <b>{ev.score}</b>/100"
    if ev.taste is not None:
        head += f" · 🎯 {round(ev.taste * 100)}%"
    if ev.explore:
        head = "🎓 <i>for training</i> · " + head
    name = ev.display_name or f"{ev.brand} {ev.model}".strip()
    title = f"<b>{html.escape(name)}</b>"
    if ev.era:
        title += f" · {html.escape(ev.era)}"

    price = listing.current_price_eur
    shipping = listing.shipping_cost_eur
    total = price + (shipping or Decimal("0"))
    mid = ev.estimated_market_value_eur
    profit = mid - total

    price_line = f"💶 <b>{money(price)}</b>"
    if shipping is not None:
        price_line += " + free shipping" if shipping == 0 else f" + {money(shipping)} shipping"
    if not is_bin:
        price_line += f" · {_bids(listing.bid_count)}"

    low, high = ev.value_low_eur, ev.value_high_eur
    market = (
        f"{_short(low)}–{money(high)}"
        if low is not None and high is not None and 0 < low <= high
        else f"≈ {money(mid)}"
    )
    multiple = f" (×{(mid / total):.1f})" if total > 0 and profit > 0 else ""
    value_line = f"📈 Market {market} → <b>{money(profit, sign=True)}</b>{multiple}"

    rarity_line = _RARITY.get(ev.rarity.value, "")
    if ev.rarity_note:
        rarity_line += f" — {html.escape(ev.rarity_note)}"

    lines = [head, title, rarity_line, "", price_line, value_line]
    if ev.web_examples and ev.web_low_eur and ev.web_high_eur:
        lines.append(
            f"🔎 Sold online: {_short(ev.web_low_eur)}–{money(ev.web_high_eur)}"
            f" ({ev.web_examples} examples)"
        )
    if ev.sales_sold:
        lines.append(
            f"📊 Our data: {_plural(ev.sales_sold, 'sale', 'sales')} in 90 days, "
            f"median {money(ev.sales_median_eur)}"
        )
    if ev.photo_seen_url:
        lines.append(
            f'📸 <a href="{html.escape(ev.photo_seen_url)}">This photo was seen in another listing</a>'
        )
    if not is_bin:
        lines.append(f"⏳ {_end_label(listing.end_time, now, tz)}")
    caption = "\n".join(lines)

    # Collapsed details, most useful first; cut to the caption budget.
    parts: list[str] = []
    if ev.why:
        parts.append("<b>Why</b>\n" + _bullets(ev.why, 3))
    elif ev.reasoning:
        parts.append(html.escape(ev.reasoning))
    if ev.story:
        parts.append("<b>Story</b>\n" + html.escape(ev.story))
    if ev.checks:
        parts.append("<b>Check</b>\n" + _bullets(ev.checks, 2))
    if ev.web_sources:
        links = " · ".join(
            f'<a href="{html.escape(u)}">{i}</a>' for i, u in enumerate(ev.web_sources[:3], 1)
        )
        parts.append(f"<b>Price sources</b>: {links}")
    parts.append(
        f"<i>Fake risk: {_risk(ev.fake_risk)} · "
        f"confidence {ev.confidence}%</i>"
    )
    room = limit - len(caption) - len("\n\n<blockquote expandable></blockquote>")
    details = _fit(parts, room)
    if details:
        caption += f"\n\n<blockquote expandable>{details}</blockquote>"
    return caption


def _short(value: Decimal) -> str:
    return money(value)


def _fit(parts: list[str], room: int) -> str:
    """Join whole parts while they fit; never cut inside an HTML tag."""
    out: list[str] = []
    used = 0
    for part in parts:
        add = len(part) + (2 if out else 0)
        if used + add > room:
            continue
        out.append(part)
        used += add
    return "\n\n".join(out)


def button_label(payload: NotificationPayload) -> str:
    source = _SOURCE.get(payload.listing.marketplace, "eBay")
    is_bin = payload.listing.buying_option == BuyingOption.FIXED_PRICE
    return f"{'Buy' if is_bin else 'Open'} on {source} →"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _bids(n: int) -> str:
    return _plural(n, "bid", "bids")


def _level(r: RarityLevel) -> str:
    return _LEVEL.get(r.value, r.value)


def _risk(r: FakeRisk) -> str:
    return _RISK.get(r.value, r.value)


# like = want it; pricey = the watch is right but the price isn't;
# dislike = not my thing; bought = would buy at this price.
FEEDBACK = {"like": "👍", "pricey": "💸", "dislike": "👎", "bought": "💰"}


def card_keyboard(
    payload: NotificationPayload, chosen: str | None = None
) -> list[list[dict[str, str]]]:
    rows = [[{"text": button_label(payload), "url": str(payload.listing.url)}]]
    if payload.evaluation_id is not None:
        rows.append(feedback_row(payload.evaluation_id, chosen))
    return rows


def feedback_row(evaluation_id: int, chosen: str | None = None) -> list[dict[str, str]]:
    return [
        {
            "text": f"{emoji} ✓" if action == chosen else emoji,
            "callback_data": f"fb:{evaluation_id}:{action}",
        }
        for action, emoji in FEEDBACK.items()
    ]
