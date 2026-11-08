"""Map raw eBay Browse API JSON → domain.Listing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from watchhunter.config.logging import get_logger
from watchhunter.domain.models import BuyingOption, Listing, Marketplace
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

        # Auctions carry the live bid in currentBidPrice and often no `price`.
        price_obj = item.get("currentBidPrice") or item.get("price") or {}
        price_val = price_obj.get("value")
        currency = (price_obj.get("currency") or "USD").upper()
        if price_val is None:
            return None
        current_price = Decimal(str(price_val))

        bid_count = int(item.get("bidCount") or 0)
        options = item.get("buyingOptions") or []
        buying_option = (
            BuyingOption.AUCTION if "AUCTION" in options else BuyingOption.FIXED_PRICE
        )
        end_time_str = item.get("itemEndDate")
        if end_time_str:
            end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
        elif buying_option == BuyingOption.FIXED_PRICE:
            # Buy It Now has no meaningful end; same convention as the HTML adapter.
            end_time = datetime.now(timezone.utc) + timedelta(days=365)
        else:
            return None

        created = item.get("itemCreationDate")
        listed_at = (
            datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None
        )

        shipping_eur: Decimal | None = None
        for opt in item.get("shippingOptions") or []:
            cost = opt.get("shippingCost") if isinstance(opt, dict) else None
            if isinstance(cost, dict) and cost.get("value") is not None:
                shipping_eur = to_eur(
                    Decimal(str(cost["value"])), (cost.get("currency") or currency).upper()
                )
                break

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
            buying_option=buying_option,
            shipping_cost_eur=shipping_eur,
            listed_at=listed_at,
        )
    except Exception as exc:
        log.warning("ebay.mapper.skip", error=str(exc), item_id=item.get("itemId"))
        return None
