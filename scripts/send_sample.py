"""Re-evaluate one stored listing with the current prompt and send its card to Telegram.

Usage:  .venv/bin/python scripts/send_sample.py <ebay item id substring>
Uses real eBay (API), OpenAI and Telegram: one evaluation call, one message.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timezone

from sqlalchemy import select

from watchhunter.application.ports.notifier import NotificationPayload
from watchhunter.config.settings import Settings
from watchhunter.container import build_container
from watchhunter.domain.models import BuyingOption, Listing
from watchhunter.infrastructure.persistence.models import ListingRow


async def main(item: str) -> None:
    c = await build_container(Settings())
    try:
        async with c.database.session() as s:
            r = await s.scalar(select(ListingRow).where(ListingRow.ebay_item_id.contains(item)))
        if r is None:
            sys.exit(f"no stored listing matching {item}")
        listing = Listing(
            external_id=r.ebay_item_id, marketplace=r.marketplace, title=r.title,
            description=r.description or "", url=r.url, current_price=r.original_price,
            currency=r.original_currency, current_price_eur=r.current_price_eur,
            bid_count=r.bid_count, end_time=r.end_time.replace(tzinfo=r.end_time.tzinfo or timezone.utc), image_urls=tuple(r.image_urls or ()),
            buying_option=BuyingOption.AUCTION if r.bid_count or r.end_time.year < 2027 else BuyingOption.FIXED_PRICE,
        )
        state = await c.marketplace.refresh_state(listing)
        listing = listing.model_copy(update={
            "current_price_eur": state.price_eur or listing.current_price_eur,
            "shipping_cost_eur": state.shipping_eur,
        })
        ev = await c.analyzer.evaluate(listing)
        print(ev.model_dump(exclude={"raw_response"}))
        await c.notifier.send(NotificationPayload(listing=listing, evaluation=ev))
        print("sent")
    finally:
        await c.aclose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
