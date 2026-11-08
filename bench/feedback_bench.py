"""Re-score the listings you rated in Telegram with the current prompts.

  .venv/bin/python bench/feedback_bench.py [min_score] [min_rarity] [max_price_eur]

For every rated listing: Jev triage verdict + gpt-5-mini verdict (no card,
no web search). Prints what the bot would send with the given thresholds
against your 👍 / 👎 / 💰.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timezone

from sqlalchemy import select

from watchhunter.config.settings import Settings
from watchhunter.container import build_container
from watchhunter.domain.evaluation import RarityLevel, Recommendation
from watchhunter.domain.models import BuyingOption, Listing, Marketplace
from watchhunter.infrastructure.persistence.models import EvaluationRow, FeedbackRow, ListingRow


async def main(min_score: int, min_rarity: str, max_price: float | None = None) -> None:
    c = await build_container(Settings())
    try:
        async with c.database.session() as s:
            rows = (await s.execute(
                select(ListingRow, FeedbackRow.action)
                .join(EvaluationRow, EvaluationRow.listing_id == ListingRow.id)
                .join(FeedbackRow, FeedbackRow.evaluation_id == EvaluationRow.id)
            )).all()
        seen, items = set(), []
        for r, action in rows:
            if r.id in seen:
                continue
            seen.add(r.id)
            items.append((Listing(
                external_id=r.ebay_item_id, marketplace=Marketplace(r.marketplace), title=r.title,
                description=r.description or "", url=r.url, current_price=r.original_price,
                currency=r.original_currency, current_price_eur=r.current_price_eur,
                bid_count=r.bid_count, end_time=r.end_time.replace(tzinfo=timezone.utc),
                image_urls=tuple(r.image_urls or ()),
                buying_option=BuyingOption.FIXED_PRICE if r.end_time.year >= 2027 else BuyingOption.AUCTION,
            ), action))
        analyzer = getattr(c.analyzer, "_evaluator", c.analyzer)
        analyzer._card_min = 101  # verdict only
        triage = await c.analyzer.triage_many([lst for lst, _ in items])
        sem = asyncio.Semaphore(8)

        async def ev(lst):
            async with sem:
                try:
                    return await analyzer.evaluate(lst)
                except Exception:
                    return None

        evals = await asyncio.gather(*(ev(lst) for lst, _ in items))
        floor = RarityLevel(min_rarity) if min_rarity else None
        tp = fp = fn = tn = 0
        for (lst, action), t, e in zip(items, triage, evals, strict=True):
            send = bool(
                t.interesting and e and e.recommendation != Recommendation.SKIP
                and e.score >= min_score and (floor is None or e.rarity.rank >= floor.rank)
                and (max_price is None or float(lst.current_price_eur) <= max_price)
            )
            liked = action in ("like", "bought")
            tp += send and liked; fp += send and not liked; fn += (not send) and liked; tn += (not send) and not liked
            if send or liked:
                print(f"{'SEND' if send else '    '} {'👍' if liked else '👎'} triage={t.interesting!s:<5} "
                      f"score={e.score if e else '-'} {e.rarity.value if e else '-':<9} "
                      f"{float(lst.current_price_eur):>6.0f}€  {lst.title[:60]}")
        print(f"\nrated {len(items)}: would send {tp + fp} (👍 {tp}, 👎 {fp}); missed 👍 {fn}; "
              f"triage passed {sum(t.interesting for t in triage)}")
    finally:
        await c.aclose()


if __name__ == "__main__":
    a = sys.argv[1:]
    asyncio.run(main(
        int(a[0]) if a else 60,
        a[1] if len(a) > 1 else "medium",
        float(a[2]) if len(a) > 2 else None,
    ))
