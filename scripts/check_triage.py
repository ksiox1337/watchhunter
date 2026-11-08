"""Live check of the triage provider against real listing titles.

Usage:  .venv/bin/python scripts/check_triage.py [N]
Reads keys from .env (TRIAGE_PROVIDER, TYPESAFE_API_KEY / OPENAI_API_KEY),
takes the N most recent listings from the local database, triages them in
one batch and prints each verdict plus the recorded cost. Never prints keys.
"""

from __future__ import annotations

import asyncio
import sys
import time

from sqlalchemy import select

from watchhunter.config.settings import Settings
from watchhunter.container import build_container
from watchhunter.domain.models import Listing
from watchhunter.infrastructure.persistence.models import ListingRow


async def main(n: int) -> None:
    settings = Settings()
    c = await build_container(settings)
    try:
        async with c.database.session() as s:
            rows = (
                await s.scalars(select(ListingRow).order_by(ListingRow.id.desc()).limit(n))
            ).all()
        listings = [
            Listing(
                external_id=r.ebay_item_id,
                marketplace=r.marketplace,
                title=r.title,
                description=r.description or "",
                url=r.url,
                current_price=r.original_price,
                currency=r.original_currency,
                current_price_eur=r.current_price_eur,
                bid_count=r.bid_count,
                end_time=r.end_time,
            )
            for r in rows
        ]
        print(f"analyzer={type(c.analyzer).__name__} listings={len(listings)}")
        t0 = time.monotonic()
        verdicts = await c.analyzer.triage_many(listings)
        dt = time.monotonic() - t0
        for lst, v in zip(listings, verdicts, strict=True):
            print(f"{'YES' if v.interesting else ' no'}  {v.reason:<28} {lst.title[:70]}")
        passed = sum(v.interesting for v in verdicts)
        print(f"\n{passed}/{len(verdicts)} passed in {dt:.1f}s")
    finally:
        await c.aclose()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 25))
