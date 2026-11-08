"""Telegram card for one find: Russian, HTML, one message with the photo on top.

Layout (sendMessage, photo as a large link preview above the text):

    🟢 ПОКУПАТЬ · Аукцион · 78/100
    Seiko A159-4019 в позолоченном корпусе
    1977 · Seiko · A159-4019

    Цена сейчас   30,50 € · 4 ставки
    С доставкой   36,00 € (доставка 5,50 €)
    Рынок         150–300 € (≈ 220 €)
    Потенциал     +184 € · ×6,1
    Окончание     сегодня 20:00 · через 1 ч 10 мин

    Почему стоит внимания
    • …
    ▸ История (expandable)
    Что проверить
    • …
    Редкость средняя · Риск подделки средний · Уверенность 70%

plus an inline "Открыть на eBay" button.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from watchhunter.application.ports.notifier import NotificationPayload
from watchhunter.domain.evaluation import FakeRisk, RarityLevel, Recommendation
from watchhunter.domain.models import BuyingOption, Marketplace

TEXT_LIMIT = 4096

_VERDICT = {
    Recommendation.BUY: "🟢 <b>ПОКУПАТЬ</b>",
    Recommendation.WATCH: "🟡 <b>ПРИСМОТРЕТЬСЯ</b>",
    Recommendation.SKIP: "⚪️ <b>ПРОПУСТИТЬ</b>",
}
_LEVEL = {"low": "низкая", "medium": "средняя", "high": "высокая"}
_RISK = {"low": "низкий", "medium": "средний", "high": "высокий"}
_SOURCE = {
    Marketplace.KLEINANZEIGEN: "Kleinanzeigen",
}


def money(value: Decimal | None, *, sign: bool = False) -> str:
    """1234.5 → '1 234,50 €' (Russian style, no decimals for round euros ≥ 100)."""
    if value is None:
        return "—"
    v = Decimal(value)
    if abs(v) >= 100:
        v = v.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        body = f"{abs(v):,.0f}"
    else:
        v = v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        body = f"{abs(v):,.2f}"
    body = body.replace(",", " ").replace(".", ",")
    prefix = ("+" if v > 0 else "−" if v < 0 else "") if sign else ("−" if v < 0 else "")
    return f"{prefix}{body} €"


def _time_left(end: datetime, now: datetime) -> str:
    minutes = int((end - now).total_seconds() // 60)
    if minutes <= 0:
        return "завершён"
    h, m = divmod(minutes, 60)
    if h >= 48:
        return f"через {h // 24} дн"
    return f"через {h} ч {m} мин" if h else f"через {m} мин"


def _end_label(end: datetime, now: datetime, tz: ZoneInfo) -> str:
    local_end, local_now = end.astimezone(tz), now.astimezone(tz)
    days = (local_end.date() - local_now.date()).days
    day = {0: "сегодня", 1: "завтра"}.get(days, local_end.strftime("%d.%m"))
    return f"{day} {local_end:%H:%M} · {_time_left(end, now)}"


def _bullets(items: tuple[str, ...], limit: int) -> str:
    return "\n".join(f"• {html.escape(x.strip().rstrip('.'))}" for x in items[:limit])


def format_card(
    payload: NotificationPayload,
    *,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> str:
    listing, ev = payload.listing, payload.evaluation
    now = now or datetime.now(timezone.utc)
    is_bin = listing.buying_option == BuyingOption.FIXED_PRICE
    source = _SOURCE.get(listing.marketplace, "eBay")

    # ── header ──────────────────────────────────────────────────────────
    kind = "Купить сейчас" if is_bin else "Аукцион"
    head = f"{_VERDICT.get(ev.recommendation, '')} · {kind} · <b>{ev.score}</b>/100"
    name = ev.display_name or f"{ev.brand} {ev.model}".strip()
    meta = " · ".join(
        x for x in (ev.era, ev.brand, ev.model if ev.model not in name else "") if x
    )
    lines = [head, "", f"<b>{html.escape(name)}</b>"]
    if meta:
        lines.append(f"<i>{html.escape(meta)}</i>")
    lines.append("")

    # ── numbers ─────────────────────────────────────────────────────────
    price = listing.current_price_eur
    shipping = listing.shipping_cost_eur
    total = price + (shipping or Decimal("0"))
    mid = ev.estimated_market_value_eur
    profit = mid - total

    price_line = f"💶 Цена сейчас: <b>{money(price)}</b>"
    if not is_bin:
        price_line += f" · {_bids(listing.bid_count)}"
    lines.append(price_line)
    if shipping is not None:
        ship = "бесплатно" if shipping == 0 else money(shipping)
        lines.append(f"🚚 С доставкой: <b>{money(total)}</b> (доставка {ship})")
    else:
        lines.append("🚚 Доставка: не указана")

    low, high = ev.value_low_eur, ev.value_high_eur
    if low is not None and high is not None and 0 < low <= high:
        lines.append(f"📈 Рынок: {money(low)}–{money(high)} (≈ {money(mid)})")
    else:
        lines.append(f"📈 Рынок: ≈ {money(mid)}")
    multiple = f" · ×{(mid / total):.1f}".replace(".", ",") if total > 0 and profit > 0 else ""
    lines.append(f"💰 Потенциал: <b>{money(profit, sign=True)}</b>{multiple}")
    if not is_bin:
        lines.append(f"⏳ Окончание: {_end_label(listing.end_time, now, tz)}")

    # ── why / story / checks ───────────────────────────────────────────
    if ev.why:
        lines += ["", "<b>Почему стоит внимания</b>", _bullets(ev.why, 4)]
    elif ev.reasoning:
        lines += ["", f"<b>Вывод:</b> {html.escape(ev.reasoning)}"]
    if ev.story:
        lines += ["", f"<blockquote expandable><b>📖 История</b>\n{html.escape(ev.story)}</blockquote>"]
    if ev.checks:
        lines += ["", "<b>Что проверить</b>", _bullets(ev.checks, 3)]
    if ev.condition:
        lines += ["", f"<b>Состояние:</b> {html.escape(ev.condition)}"]

    lines += [
        "",
        f"<i>Редкость {_level(ev.rarity)} · риск подделки {_risk(ev.fake_risk)} · "
        f"уверенность {ev.confidence}% · {source}</i>",
    ]
    text = "\n".join(lines)
    if len(text) > TEXT_LIMIT:  # drop the least important block first
        text = text.replace(f"\n\n<b>Состояние:</b> {html.escape(ev.condition)}", "")
    return text[:TEXT_LIMIT]


def button_label(payload: NotificationPayload) -> str:
    source = _SOURCE.get(payload.listing.marketplace, "eBay")
    is_bin = payload.listing.buying_option == BuyingOption.FIXED_PRICE
    return f"{'Купить' if is_bin else 'Открыть'} на {source} →"


def _bids(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        word = "ставка"
    elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        word = "ставки"
    else:
        word = "ставок"
    return f"{n} {word}"


def _level(r: RarityLevel) -> str:
    return _LEVEL.get(r.value, r.value)


def _risk(r: FakeRisk) -> str:
    return _RISK.get(r.value, r.value)
