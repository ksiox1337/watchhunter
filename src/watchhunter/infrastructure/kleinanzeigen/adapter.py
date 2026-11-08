"""Kleinanzeigen (formerly eBay Kleinanzeigen) MarketplacePort adapter.

Kleinanzeigen is Germany's largest classifieds site — pure fixed-price listings,
no auctions. The bot uses this as a watchdog for freshly-listed items:
sort by newest, scan often, analyze each item exactly once.

Site structure (kleinanzeigen.de):
  • Search URL: https://www.kleinanzeigen.de/s-suchanfrage.html?keywords=…
                or  https://www.kleinanzeigen.de/s-<keyword>/k0
  • Sort by newest:    &sortingField=POSTING_DATE
  • Result list item:  <article class="aditem" data-adid="123456789">
  • Item page URL:     /s-anzeige/<slug>/<id>
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote_plus

from bs4 import BeautifulSoup, Tag
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from watchhunter.application.ports.marketplace import (
    ListingState,
    MarketplacePort,
    MarketplaceQuery,
)
from watchhunter.config.logging import get_logger
from watchhunter.domain.models import BuyingOption, Listing, Marketplace
from watchhunter.infrastructure.http.client import HttpClient
from watchhunter.infrastructure.ratelimit.limiter import RateLimiter

log = get_logger(__name__)

_HOST = "www.kleinanzeigen.de"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)
_BASE_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
}

# Sentinel for "seller won't ship / pickup-only" — same value the eBay
# adapter uses, so the same MAX_SHIPPING_EUR cap rejects both.
_INELIGIBLE_SHIPPING = Decimal("99999")


class KleinanzeigenMarketplaceAdapter(MarketplacePort):
    def __init__(
        self,
        *,
        http: HttpClient,
        rate_limiter: RateLimiter,
        pages_per_query: int = 1,
    ) -> None:
        self._http = http
        self._rate = rate_limiter
        self._pages = max(1, pages_per_query)

    # ─── search ───────────────────────────────────────────────────────────
    async def search_auctions(
        self, query: MarketplaceQuery
    ) -> AsyncIterator[Listing]:
        if query.marketplace != Marketplace.KLEINANZEIGEN:
            log.warning("ka.unsupported_marketplace", marketplace=query.marketplace.value)
            return
        pages = max(1, query.max_pages if query.max_pages is not None else self._pages)

        seen: set[str] = set()
        for keyword in query.keywords:
            for page in range(1, pages + 1):
                async with self._rate:
                    html = await self._fetch_search_page(
                        keyword, page, query.max_price_eur
                    )
                if not html:
                    continue
                for listing in self._parse_search_html(
                    html=html, keyword=keyword, page=page
                ):
                    if listing.dedup_key in seen:
                        continue
                    seen.add(listing.dedup_key)
                    yield listing
        log.info("ka.scan.done", yielded=len(seen))

    async def _fetch_search_page(
        self,
        keyword: str,
        page: int,
        max_price_eur: Decimal | None,
    ) -> str:
        # Path-based pagination: /seite:N/<keyword>/k0
        seite = f"seite:{page}/" if page > 1 else ""
        path_kw = quote_plus(keyword)
        url = (
            f"https://{_HOST}/s-{seite}{path_kw}/k0"
            f"?sortingField=POSTING_DATE"
        )
        if max_price_eur is not None:
            url += f"&maxPrice={int(max_price_eur)}"

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(min=1, max=8),
                retry=retry_if_exception_type(Exception),
                reraise=True,
            ):
                with attempt:
                    async with self._http.session.get(url, headers=_BASE_HEADERS) as resp:
                        if resp.status >= 400:
                            raise RuntimeError(f"HTTP {resp.status}")
                        return await resp.text()
        except Exception as exc:
            log.warning("ka.fetch_failed", url=url, error=str(exc))
            return ""
        return ""

    # ─── parse ────────────────────────────────────────────────────────────
    def _parse_search_html(
        self, *, html: str, keyword: str, page: int
    ) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        # Kleinanzeigen migrated to an Astro frontend; cards are now bare
        # <article data-adid="…"> with utility-class styling and `data-href`
        # carrying the item URL.
        cards = soup.select("article[data-adid], article.aditem")
        parsed: list[Listing] = []
        for card in cards:
            listing = self._parse_card(card)
            if listing is not None:
                parsed.append(listing)
        log.info(
            "ka.page_parsed",
            keyword=keyword,
            page=page,
            html_kb=len(html) // 1024,
            raw_items=len(cards),
            parsed=len(parsed),
        )
        # One-shot diagnostic dump when nothing parses — same workflow as eBay.
        if len(cards) == 0:
            from pathlib import Path

            dump = Path(f"/tmp/ka_dump_{keyword}_{page}.html")
            try:
                if not dump.exists():
                    dump.write_text(html)
                    log.warning("ka.debug_dump_written", path=str(dump))
            except Exception:
                pass
        return parsed

    def _parse_card(self, card: Tag) -> Listing | None:
        try:
            ext_id = (card.get("data-adid") or "").strip()
            if not ext_id:
                return None

            # URL — Astro layout carries it as data-href on the article;
            # legacy layout has a child <a class="ellipsis">.
            href = (card.get("data-href") or "").strip()
            if not href:
                link = card.select_one("a[href*='/s-anzeige/']")
                if link and link.get("href"):
                    href = str(link["href"])
            if not href:
                return None
            href = href.split("?")[0]
            url = href if href.startswith("http") else f"https://{_HOST}{href}"

            # Title — Astro uses <h3>; legacy used <a class="ellipsis">.
            title_el = (
                card.select_one("h3, h2")
                or card.select_one("a.ellipsis, a[href*='/s-anzeige/']")
            )
            title = title_el.get_text(" ", strip=True) if title_el else ""
            if not title:
                return None

            # Price — Astro tag is <p class="… text-title3">; legacy was
            # .aditem-main--middle--price-shipping--price. Either way the
            # text matches "<number> €" / "<number> € VB" / "Zu verschenken".
            price_el = card.select_one(
                "p.text-title3, .aditem-main--middle--price-shipping--price"
            )
            if price_el is None:
                # Fallback: scan all <p> for one with a price-shaped string.
                for p in card.find_all("p"):
                    if "€" in p.get_text():
                        price_el = p
                        break
            price_text = price_el.get_text(" ", strip=True) if price_el else ""
            current_price = _parse_kleinanzeigen_price(price_text)
            if current_price is None:
                return None

            # Shipping — Kleinanzeigen cards show "Versand möglich" / "Nur
            # Abholung" but not the actual cost; that lives on the item page.
            shipping = _shipping_from_card_text(card.get_text(" ", strip=True))

            # Image
            image_urls: tuple[str, ...] = ()
            img = card.select_one(
                "img[src*='img.kleinanzeigen.de'], .aditem-image img, .imagebox img, img"
            )
            if img:
                src = (
                    img.get("src")
                    or img.get("data-src")
                    or img.get("data-imgsrc")
                )
                if src and not str(src).startswith("data:"):
                    image_urls = (str(src),)

            # Description preview — Astro uses <p class="text-bodyRegular">.
            desc_el = card.select_one(
                "p.text-bodyRegular, .aditem-main--middle--description"
            )
            description = desc_el.get_text(" ", strip=True) if desc_el else ""

            # Kleinanzeigen items don't have an end time. Use a far-future
            # sentinel so the auction-window filter (which we bypass for
            # FIXED_PRICE anyway) never rejects them.
            end_time = datetime.now(timezone.utc) + timedelta(days=365)

            return Listing(
                external_id=ext_id,
                marketplace=Marketplace.KLEINANZEIGEN,
                title=title,
                description=description,
                url=url,  # type: ignore[arg-type]
                current_price=current_price,
                currency="EUR",
                current_price_eur=current_price,
                bid_count=0,
                end_time=end_time,
                image_urls=image_urls,  # type: ignore[arg-type]
                buying_option=BuyingOption.FIXED_PRICE,
                shipping_cost_eur=shipping,
            )
        except Exception as exc:
            log.debug("ka.card_parse_skip", error=str(exc))
            return None

    # ─── refresh_state (item-page price + shipping) ───────────────────────
    async def refresh_state(self, listing: Listing) -> ListingState:
        url = (
            listing.url.unicode_string()
            if hasattr(listing.url, "unicode_string")
            else str(listing.url)
        )
        try:
            async with self._rate:
                async with self._http.session.get(url, headers=_BASE_HEADERS) as resp:
                    if resp.status == 404:
                        return ListingState(price_eur=None, shipping_eur=None)
                    if resp.status >= 400:
                        return ListingState(
                            price_eur=listing.current_price_eur,
                            shipping_eur=listing.shipping_cost_eur,
                        )
                    html = await resp.text()
        except Exception as exc:
            log.warning("ka.refresh_failed", error=str(exc))
            return ListingState(
                price_eur=listing.current_price_eur,
                shipping_eur=listing.shipping_cost_eur,
            )

        if len(html) < 3000:
            return ListingState(
                price_eur=listing.current_price_eur,
                shipping_eur=listing.shipping_cost_eur,
            )

        soup = BeautifulSoup(html, "lxml")
        price = _extract_item_price(soup) or listing.current_price_eur
        shipping = _extract_item_shipping(soup) or listing.shipping_cost_eur
        return ListingState(price_eur=price, shipping_eur=shipping)

    # ─── fetch_gallery (item-page additional photos) ──────────────────────
    async def fetch_gallery(
        self, listing: Listing, max_images: int
    ) -> tuple[str, ...]:
        url = (
            listing.url.unicode_string()
            if hasattr(listing.url, "unicode_string")
            else str(listing.url)
        )
        try:
            async with self._rate:
                async with self._http.session.get(url, headers=_BASE_HEADERS) as resp:
                    if resp.status != 200:
                        return ()
                    html = await resp.text()
        except Exception as exc:
            log.warning("ka.gallery_fetch_failed", error=str(exc))
            return ()

        if len(html) < 3000:
            return ()

        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        for sel in (
            "#viewad-image img",
            ".galleryimage-large img",
            "#viewad-thumbnails img",
            ".vip-gallery img",
        ):
            for img in soup.select(sel):
                src = (
                    img.get("data-imgsrc")
                    or img.get("data-src")
                    or img.get("src")
                )
                if not src:
                    continue
                s = str(src)
                if s.startswith("data:"):
                    continue
                # Promote thumbnail size to large where the URL pattern allows
                s = re.sub(r"\$_\d+(?=\.(jpg|jpeg|png|webp))", "$_72", s, flags=re.I)
                if s not in urls:
                    urls.append(s)
        return tuple(urls[:max_images])


# ─── price helpers ───────────────────────────────────────────────────────
_PRICE_RE = re.compile(r"([\d.,]+)\s*€?", re.IGNORECASE)


def _parse_kleinanzeigen_price(text: str) -> Decimal | None:
    """Parse 'EUR 45,00', '45 €', '12 € VB', 'Zu verschenken', etc."""
    text = text.strip()
    if not text:
        return None
    lower = text.lower()
    if "verschenken" in lower or "zu verschenken" in lower:
        return Decimal("0")
    if "auf anfrage" in lower or "preis nach absprache" in lower:
        return None

    # German format: "1.234,56" or "1234,56" or just "45"
    m = _PRICE_RE.search(text)
    if not m:
        return None
    raw = m.group(1)
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        if raw.count(",") == 1 and len(raw.split(",")[1]) == 2:
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


# ─── shipping helpers ────────────────────────────────────────────────────
_PICKUP_ONLY_RE = re.compile(
    r"(?:Nur\s*Abholung|Abholung\s*nur|Nur\s*Selbstabholung|"
    r"Verkauf\s*nur\s*an\s*Selbstabholer)",
    re.IGNORECASE,
)
_VERSAND_MOEGLICH_RE = re.compile(r"Versand\s*m[oö]glich", re.IGNORECASE)
_VERSAND_COST_RE = re.compile(
    r"(?:Versand(?:kosten)?|\+\s*Versand)\s*:?\s*([\d.,]+)\s*€",
    re.IGNORECASE,
)


def _shipping_from_card_text(text: str) -> Decimal | None:
    if _PICKUP_ONLY_RE.search(text):
        return _INELIGIBLE_SHIPPING
    m = _VERSAND_COST_RE.search(text)
    if m:
        val = _parse_kleinanzeigen_price(m.group(1))
        return val if val is not None else None
    # "Versand möglich" without a price — leave as unknown
    return None


def _extract_item_price(soup: BeautifulSoup) -> Decimal | None:
    for sel in (
        "h2#viewad-price",
        "#viewad-price",
        "[data-testid='ad-price']",
        ".aditem-main--middle--price-shipping--price",
    ):
        el = soup.select_one(sel)
        if el:
            v = _parse_kleinanzeigen_price(el.get_text(" ", strip=True))
            if v is not None:
                return v
    return None


def _extract_item_shipping(soup: BeautifulSoup) -> Decimal | None:
    full_text = soup.get_text(" ", strip=True)
    if _PICKUP_ONLY_RE.search(full_text):
        return _INELIGIBLE_SHIPPING
    # Explicit "Versandkosten: 4,90 €"
    m = _VERSAND_COST_RE.search(full_text)
    if m:
        return _parse_kleinanzeigen_price(m.group(1))
    # "Versand möglich" with no number → unknown (None — caller falls back)
    if _VERSAND_MOEGLICH_RE.search(full_text):
        return None
    # No shipping mentioned at all → likely pickup-only
    return _INELIGIBLE_SHIPPING
