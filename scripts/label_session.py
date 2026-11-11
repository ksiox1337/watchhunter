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
import os
import random
import sys
from decimal import Decimal

from watchhunter.application.ports.marketplace import MarketplaceQuery
from watchhunter.application.ports.notifier import NotificationPayload
from watchhunter.config.settings import Settings
from watchhunter.container import build_container
from watchhunter.domain.models import BuyingOption, Listing, Marketplace

PRICE_BUCKETS = [(0, 20), (20, 40), (40, 70), (70, 200), (200, 100_000)]
MAX_PRICE = Decimal(os.environ.get("LABEL_MAX_PRICE", "70"))  # live bot cap by default
# Optional focus: LABEL_KEYWORDS="casio vintage,casio databank" replaces the keywords
# of every source, LABEL_BRAND=casio keeps only listings whose title names it.
FOCUS = [k.strip() for k in os.environ.get("LABEL_KEYWORDS", "").split(",") if k.strip()]
BRAND = os.environ.get("LABEL_BRAND", "").lower()


async def gather_pool(c, s: Settings) -> list[Listing]:
    pool: dict[str, Listing] = {}
    queries = [
        (BuyingOption.AUCTION, FOCUS or s.ebay_keywords, 3),
        (BuyingOption.FIXED_PRICE, FOCUS or s.buy_now_keywords, 2),
    ]
    for option, keywords, pages in queries:
        for market in s.ebay_marketplaces:
            for cat in s.ebay_category_ids or [None]:
                q = MarketplaceQuery(
                    marketplace=Marketplace(market), category_id=cat, keywords=keywords,
                    ends_within_hours=s.auction_ends_within_hours, only_with_bids=False,
                    max_price_eur=MAX_PRICE, buying_option=option, max_pages=pages,
                )
                async for lst in c.marketplace.search_auctions(q):
                    if lst.image_urls and lst.hours_until_end > 0.2:
                        pool.setdefault(lst.external_id, lst)
    return list(pool.values())


async def gather_kleinanzeigen(c, s: Settings, pages: int = 2) -> list[Listing]:
    from watchhunter.infrastructure.kleinanzeigen.adapter import KleinanzeigenMarketplaceAdapter
    from watchhunter.infrastructure.ratelimit.limiter import RateLimiter

    ka = KleinanzeigenMarketplaceAdapter(http=c.http, rate_limiter=RateLimiter(rate_per_minute=8))
    q = MarketplaceQuery(
        marketplace=Marketplace.KLEINANZEIGEN, category_id=None, keywords=FOCUS or s.kleinanzeigen_keywords,
        ends_within_hours=24, only_with_bids=False, max_price_eur=MAX_PRICE,
        buying_option=BuyingOption.FIXED_PRICE, max_pages=pages,
    )
    return [lst async for lst in ka.search_auctions(q) if lst.image_urls]


def pick(pool: list[Listing], n: int) -> list[Listing]:
    """Even spread over price buckets x buying option; random inside each cell."""
    rng = random.Random(7)
    cells: dict[tuple[int, str], list[Listing]] = {}
    for lst in pool:
        b = next(i for i, (lo, hi) in enumerate(PRICE_BUCKETS) if lo <= lst.current_price_eur < hi)
        cells.setdefault((b, lst.marketplace.value), []).append(lst)
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
        ebay = await gather_pool(c, s)
        ka = await gather_kleinanzeigen(c, s)
        print(f"eBay {len(ebay)}, Kleinanzeigen {len(ka)}")
        pool = [x for x in ebay + ka if BRAND in x.title.lower()]
        # Never ask twice: skip anything already sent (rated sessions, finds).
        pool = [x for x in pool if not await c.repository.was_ever_notified(x.external_id)]
        chosen = pick(pool, n)
        print(f"pool {len(pool)} -> sending {len(chosen)}")
        analyzer = getattr(c.analyzer, "_evaluator", c.analyzer)
        saved_card_min = analyzer._card_min
        analyzer._card_min = 101  # verdict only: no card step, no web search
        await c.notifier._client.send_message(  # type: ignore[attr-defined]
            text=(
                f"<b>Labeling: {len(chosen)} listings</b>\n"
                "👍 interesting · 💸 right watch, wrong price · 👎 not for me · 💰 would buy"
            )
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
