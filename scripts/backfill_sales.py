"""Start the sale history from auctions already evaluated, then close ended ones.

Usage: .venv/bin/python scripts/backfill_sales.py
"""

from __future__ import annotations

import asyncio
from datetime import timezone

from sqlalchemy import select

from watchhunter.config.settings import Settings
from watchhunter.container import build_container
from watchhunter.domain.models import BuyingOption, Listing, Marketplace
from watchhunter.infrastructure.persistence.models import EvaluationRow, ListingRow
from watchhunter.infrastructure.persistence.repository import _row_to_eval
from watchhunter.sales.repository import SalesRepository
from watchhunter.sales.tracker import SalesTracker


async def main() -> None:
    c = await build_container(Settings())
    repo = SalesRepository(c.database)
    try:
        async with c.database.session() as s:
            rows = (await s.execute(
                select(ListingRow, EvaluationRow).join(EvaluationRow, EvaluationRow.listing_id == ListingRow.id)
            )).all()
        n = 0
        for r, e in rows:
            if not r.ebay_item_id.startswith("v1|") or r.end_time.year >= 2027:
                continue  # eBay auctions only (Buy It Now ends a year out)
            lst = Listing(
                external_id=r.ebay_item_id, marketplace=Marketplace(r.marketplace), title=r.title,
                url=r.url, current_price=r.original_price, currency=r.original_currency,
                current_price_eur=r.current_price_eur, bid_count=r.bid_count,
                end_time=r.end_time.replace(tzinfo=r.end_time.tzinfo or timezone.utc),
                buying_option=BuyingOption.AUCTION,
            )
            await repo.track(lst, _row_to_eval(e))
            n += 1
        print("tracked", n)
        print(await SalesTracker(repository=repo, marketplace=c.marketplace).execute())
    finally:
        await c.aclose()


asyncio.run(main())
