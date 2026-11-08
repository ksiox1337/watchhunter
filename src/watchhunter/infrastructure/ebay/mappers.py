"""Map raw eBay Browse API JSON → domain.Listing."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from watchhunter.config.logging import get_logger
from watchhunter.domain.models import Listing, Marketplace
from watchhunter.infrastructure.ebay.currency import to_eur

log = get_logger(__name__)


def parse_summary(
    item: dict[str, Any], marketplace: Marketplace
) -> Listing | None:
    """Convert one item summary from /item_summary/search to a Listing."""
    try:
        external_id = item.get("itemId") or item.get("legacyItemId")
        if not external_id:
            return None

        title = (item.get("title") or "").strip()
        description = (item.get("shortDescription") or "").strip()
        url = item.get("itemWebUrl") or item.get("itemHref")
        if not url or not title:
            return None

        price_obj = item.get("price") or {}
        price_val = price_obj.get("value")
        currency = (price_obj.get("currency") or "USD").upper()
        if price_val is None:
            return None
        current_price = Decimal(str(price_val))

        bid_count = int(item.get("bidCount") or 0)
        end_time_str = item.get("itemEndDate")
        if not end_time_str:
            return None
        end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))

        images: list[str] = []
        primary = (item.get("image") or {}).get("imageUrl")
        if primary:
            images.append(primary)
        for extra in item.get("additionalImages") or []:
            iu = extra.get("imageUrl") if isinstance(extra, dict) else None
            if iu and iu not in images:
                images.append(iu)

        return Listing(
            external_id=str(external_id),
            marketplace=marketplace,
            title=title,
            description=description,
            url=url,  # type: ignore[arg-type]
            current_price=current_price,
            currency=currency,
            current_price_eur=to_eur(current_price, currency),
            bid_count=bid_count,
            end_time=end_time,
            image_urls=tuple(images),  # type: ignore[arg-type]
        )
    except Exception as exc:
        log.warning("ebay.mapper.skip", error=str(exc), item_id=item.get("itemId"))
        return None
