"""Labeling session: send N varied live eBay listings as cards with feedback buttons.

Usage:  .venv/bin/python scripts/label_session.py [N]

Picks listings across sources and prices on purpose (auctions + Buy It Now,
cheap to expensive, including ones the triage would normally drop), runs the
verdict step only (no web search, no long card text: ~$0.0005 each) and sends
each card with 👍 / 👎 / 💰. Your taps land in the `feedback` table and become
the training/benchmark set for what you actually want.

Sent evaluations are stored with raw_response.labeling = true and marked as
notified, so the running bot never sends them again.
"""

from __future__ import annotations

import asyncio
import random
import sys

from watchhunter.application.ports.marketplace import MarketplaceQuery
from watchhunter.application.ports.notifier import NotificationPayload
from watchhunter.config.settings import Settings
from watchhunter.container import build_container
from watchhunter.domain.models import BuyingOption, Listing, Marketplace

PRICE_BUCKETS = [(0, 30), (30, 80), (80, 200), (200, 600), (600, 100_000)]


async def gather_pool(c, s: Settings) -> list[Listing]:
    pool: dict[str, Listing] = {}
    queries = [
        (BuyingOption.AUCTION, s.ebay_keywords, 3),
        (BuyingOption.FIXED_PRICE, s.buy_now_keywords, 2),
    ]
    for option, keywords, pages in queries:
        for market in s.ebay_marketplaces:
            for cat in s.ebay_category_ids or [None]:
                q = MarketplaceQuery(
                    marketplace=Marketplace(market), category_id=cat, keywords=keywords,
                    ends_within_hours=s.auction_ends_within_hours, only_with_bids=False,
                    max_price_eur=None, buying_option=option, max_pages=pages,
                )
                async for lst in c.marketplace.search_auctions(q):
                    if lst.image_urls and lst.hours_until_end > 0.2:
                        pool.setdefault(lst.external_id, lst)
    return list(pool.values())


def pick(pool: list[Listing], n: int) -> list[Listing]:
    """Even spread over price buckets x buying option; random inside each cell."""
    rng = random.Random(7)
    cells: dict[tuple[int, str], list[Listing]] = {}
    for lst in pool:
        b = next(i for i, (lo, hi) in enumerate(PRICE_BUCKETS) if lo <= lst.current_price_eur < hi)
        cells.setdefault((b, lst.buying_option.value), []).append(lst)
    for v in cells.values():
        rng.shuffle(v)
    out: list[Listing] = []
    while len(out) < n and any(cells.values()):
        for key in sorted(cells):
            if cells[key] and len(out) < n:
                out.append(cells[key].pop())
    rng.shuffle(out)
    return out


async def main(n: int) -> None:
    s = Settings()
    c = await build_container(s)
    try:
        pool = await gather_pool(c, s)
        # Never ask twice: skip anything already sent (rated sessions, finds).
        pool = [x for x in pool if not await c.repository.was_ever_notified(x.external_id)]
        chosen = pick(pool, n)
        print(f"pool {len(pool)} -> sending {len(chosen)}")
        analyzer = getattr(c.analyzer, "_evaluator", c.analyzer)
        saved_card_min = analyzer._card_min
        analyzer._card_min = 101  # verdict only: no card step, no web search
        await c.notifier._client.send_message(  # type: ignore[attr-defined]
            text=f"<b>Разметка: {len(chosen)} лотов</b>\nОцени каждый: 👍 интересно · 👎 мимо · 💰 купил бы"
        )
        sem = asyncio.Semaphore(6)

        async def evaluate(lst: Listing):
            async with sem:
                try:
                    return lst, await analyzer.evaluate(lst)
                except Exception as exc:
                    print("eval failed", lst.external_id, str(exc)[:80])
                    return lst, None

        results = await asyncio.gather(*(evaluate(x) for x in chosen))
        analyzer._card_min = saved_card_min
        sent = 0
        for i, (lst, ev) in enumerate(results, 1):
            if ev is None:
                continue
            ev = ev.model_copy(update={"raw_response": {**ev.raw_response, "labeling": True}})
            lid = await c.repository.upsert_listing(lst)
            eid = await c.repository.save_evaluation(lid, ev)
            try:
                await c.notifier.send(NotificationPayload(listing=lst, evaluation=ev, evaluation_id=eid))
                await c.repository.mark_notified(eid)
                sent += 1
            except Exception as exc:
                print("send failed", lst.external_id, str(exc)[:80])
            print(f"{i}/{len(results)} sent")
            await asyncio.sleep(1.2)
        print(f"done: {sent} sent")
    finally:
        await c.aclose()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 100))
