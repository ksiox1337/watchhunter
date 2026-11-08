"""HTML fallback adapter — used when EBAY_USE_API=false.

Scrapes eBay's public auction search results. This is best-effort and
intended only as a placeholder until proper API credentials are available.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote_plus

import aiohttp
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
from watchhunter.infrastructure.ebay.currency import to_eur
from watchhunter.infrastructure.http.client import HttpClient
from watchhunter.infrastructure.ratelimit.limiter import RateLimiter

log = get_logger(__name__)


# Marketplace → (host, default currency, Accept-Language header).
_MARKETPLACE_HOSTS: dict[Marketplace, tuple[str, str, str]] = {
    Marketplace.EBAY_US: ("www.ebay.com", "USD", "en-US,en;q=0.9"),
    Marketplace.EBAY_DE: ("www.ebay.de", "EUR", "de-DE,de;q=0.9,en;q=0.6"),
    Marketplace.EBAY_GB: ("www.ebay.co.uk", "GBP", "en-GB,en;q=0.9"),
    Marketplace.EBAY_FR: ("www.ebay.fr", "EUR", "fr-FR,fr;q=0.9,en;q=0.6"),
    Marketplace.EBAY_IT: ("www.ebay.it", "EUR", "it-IT,it;q=0.9,en;q=0.6"),
}

# Pretend to be Chrome — eBay aggressively blocks unrecognised UAs.
_BLOCK_MIN_S = 300.0
_BLOCK_MAX_S = 3600.0


class _Transient(Exception):
    """Network error / 5xx worth a quick retry (never a bot block)."""


def _is_challenge(html: str) -> bool:
    """eBay's bot-check interstitial: tiny page with the splashui challenge."""
    return len(html) < 20_000 and ("splashui" in html or "challenge" in html.lower())


_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)

# Currency symbols → ISO codes. eBay sometimes prefixes with locale strings.
_CURRENCY_SYMBOLS: dict[str, str] = {
    "$": "USD",
    "US $": "USD",
    "EUR": "EUR",
    "€": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "CHF": "CHF",
    "JPY": "JPY",
}


class EbayHtmlMarketplaceAdapter(MarketplacePort):
    """Scrape eBay search HTML for auctions ending soon with bids.

    Filters used in the URL:
      - LH_Auction=1     → auction only
      - LH_HasBids=1     → must have bids
      - _sop=1           → sort: ending soonest
      - _udlo / _udhi    → price bounds (unused in MVP)
    """

    def __init__(
        self,
        *,
        http: HttpClient,
        rate_limiter: RateLimiter,
        pages_per_query: int = 2,
    ) -> None:
        self._http = http
        self._rate = rate_limiter
        self._pages = max(1, pages_per_query)
        # Bot-challenge cooldown shared by every job using this adapter: once
        # eBay serves its "Pardon our interruption" page or a 403, more
        # requests only extend the block, so all eBay traffic pauses.
        self._blocked_until = 0.0
        self._block_s = _BLOCK_MIN_S
        self._last_out_of_window = 0

    def _blocked(self) -> bool:
        return time.monotonic() < self._blocked_until

    def _note_block(self, reason: str) -> None:
        if self._blocked():
            return
        self._blocked_until = time.monotonic() + self._block_s
        log.warning("ebay.html.blocked", reason=reason, pause_s=int(self._block_s))
        self._block_s = min(self._block_s * 2, _BLOCK_MAX_S)

    def _note_ok(self) -> None:
        self._block_s = _BLOCK_MIN_S

    async def fetch_gallery(
        self, listing: Listing, max_images: int
    ) -> tuple[str, ...]:
        host_info = _MARKETPLACE_HOSTS.get(listing.marketplace)
        if not host_info:
            return ()
        host, _, accept_language = host_info
        url = f"https://{host}/itm/{listing.external_id}"
        headers = {
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": accept_language,
            "Accept-Encoding": "gzip, deflate, br",
        }
        if self._blocked():
            return ()
        try:
            async with self._rate:
                async with self._http.session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        return ()
                    html = await resp.text()
        except Exception as exc:
            log.warning("ebay.html.gallery_fetch_failed", error=str(exc))
            return ()

        if len(html) < 5000:
            return ()

        soup = BeautifulSoup(html, "lxml")
        return _extract_gallery_images(soup, max_images)

    async def refresh_state(self, listing: Listing) -> ListingState:
        host_info = _MARKETPLACE_HOSTS.get(listing.marketplace)
        if not host_info:
            return ListingState(
                price_eur=listing.current_price_eur,
                shipping_eur=listing.shipping_cost_eur,
            )
        host, default_currency, accept_language = host_info

        url = f"https://{host}/itm/{listing.external_id}"
        headers = {
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": accept_language,
            "Accept-Encoding": "gzip, deflate, br",
        }
        if self._blocked():
            return ListingState(
                price_eur=listing.current_price_eur,
                shipping_eur=listing.shipping_cost_eur,
            )
        try:
            async with self._rate:
                async with self._http.session.get(url, headers=headers) as resp:
                    if resp.status == 404:
                        return ListingState(price_eur=None, shipping_eur=None)
                    if resp.status >= 400:
                        log.warning("ebay.html.refresh_status", status=resp.status, url=url)
                        return ListingState(
                            price_eur=listing.current_price_eur,
                            shipping_eur=listing.shipping_cost_eur,
                        )
                    html = await resp.text()
        except Exception as exc:
            log.warning("ebay.html.refresh_failed", error=str(exc), url=url)
            return ListingState(
                price_eur=listing.current_price_eur,
                shipping_eur=listing.shipping_cost_eur,
            )

        # Small response = captcha / sorry page; degrade to stored snapshot.
        if len(html) < 5000:
            log.warning("ebay.html.refresh_too_small", bytes=len(html), url=url)
            return ListingState(
                price_eur=listing.current_price_eur,
                shipping_eur=listing.shipping_cost_eur,
            )

        soup = BeautifulSoup(html, "lxml")
        page_text = soup.get_text(" ", strip=True)

        price = _extract_current_price(soup, default_currency)
        if price is None:
            log.debug("ebay.html.refresh_no_price", url=url)
            price = listing.current_price_eur

        shipping = _extract_item_page_shipping(soup, page_text, default_currency)
        if shipping is None:
            # Don't lose the card-time value just because the item page
            # parser missed; the search-card number is still better than None.
            shipping = listing.shipping_cost_eur

        return ListingState(price_eur=price, shipping_eur=shipping)

    async def search_auctions(
        self, query: MarketplaceQuery
    ) -> AsyncIterator[Listing]:
        host_info = _MARKETPLACE_HOSTS.get(query.marketplace)
        if not host_info:
            log.warning("ebay.html.unsupported_marketplace", marketplace=query.marketplace.value)
            return
        host, default_currency, accept_language = host_info

        seen: set[str] = set()
        pages = max(1, query.max_pages if query.max_pages is not None else self._pages)
        for keyword in query.keywords:
            for page in range(1, pages + 1):
                if self._blocked():
                    log.info("ebay.html.scan.paused", marketplace=query.marketplace.value)
                    return
                async with self._rate:
                    html = await self._fetch_search_page(
                        host=host,
                        keyword=keyword,
                        page=page,
                        max_price_eur=query.max_price_eur,
                        accept_language=accept_language,
                        buying_option=query.buying_option,
                    )
                if not html:
                    continue
                for listing in self._parse_search_html(
                    html=html,
                    host=host,
                    marketplace=query.marketplace,
                    default_currency=default_currency,
                    ends_within_hours=query.ends_within_hours,
                    keyword=keyword,
                    page=page,
                    buying_option=query.buying_option,
                ):
                    if (
                        query.buying_option == BuyingOption.AUCTION
                        and query.only_with_bids
                        and listing.bid_count <= 0
                    ):
                        continue
                    if listing.dedup_key in seen:
                        continue
                    seen.add(listing.dedup_key)
                    yield listing
                # Auctions are sorted ending-soonest: once a page reaches past
                # the time window, every later page is outside it too.
                if (
                    query.buying_option == BuyingOption.AUCTION
                    and self._last_out_of_window > 0
                ):
                    break
                # be polite
                await asyncio.sleep(0.5)
        log.info(
            "ebay.html.scan.done",
            marketplace=query.marketplace.value,
            yielded=len(seen),
        )

    # ─── HTTP ─────────────────────────────────────────────────────────────
    async def _fetch_search_page(
        self,
        *,
        host: str,
        keyword: str,
        page: int,
        max_price_eur: Decimal | None,
        accept_language: str,
        buying_option: BuyingOption,
    ) -> str:
        # _sop=1  = ending soonest    (for auctions)
        # _sop=10 = newly listed      (for Buy It Now — fresh-listing hunting)
        # LH_BIN=1 = Buy It Now only; LH_Auction=1 + LH_HasBids=1 = bidded auctions
        if buying_option == BuyingOption.FIXED_PRICE:
            buying_filter = "&LH_BIN=1"
            sort = "&_sop=10"
        else:
            buying_filter = "&LH_Auction=1&LH_HasBids=1"
            sort = "&_sop=1"

        url = (
            f"https://{host}/sch/i.html"
            f"?_nkw={quote_plus(keyword)}"
            f"&_sacat=0"
            f"{buying_filter}"
            f"{sort}"
            f"&_pgn={page}"
        )
        if max_price_eur is not None:
            url += f"&_udhi={int(max_price_eur)}"
        headers = {
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": accept_language,
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(min=1, max=8),
                retry=retry_if_exception_type((_Transient, aiohttp.ClientError, asyncio.TimeoutError)),
                reraise=True,
            ):
                with attempt:
                    async with self._http.session.get(url, headers=headers) as resp:
                        if resp.status in (403, 429):
                            # Retrying a block right away only deepens it.
                            self._note_block(f"HTTP {resp.status}")
                            return ""
                        if resp.status >= 400:
                            raise _Transient(f"HTTP {resp.status}")
                        html = await resp.text()
                    if _is_challenge(html):
                        self._note_block("challenge page")
                        return ""
                    self._note_ok()
                    return html
        except Exception as exc:
            log.warning("ebay.html.fetch_failed", url=url, error=str(exc))
            return ""
        return ""

    # ─── Parse ────────────────────────────────────────────────────────────
    def _parse_search_html(
        self,
        *,
        html: str,
        host: str,
        marketplace: Marketplace,
        default_currency: str,
        ends_within_hours: int,
        keyword: str,
        page: int,
        buying_option: BuyingOption,
    ) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        results: list[Listing] = []
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=ends_within_hours)

        # eBay's current SRP uses .s-card; older layouts used .s-item.
        # Match both, deduped by element identity.
        candidates = soup.select("li.s-card, div.s-card, li.s-item, div.s-item")
        parsed = 0
        out_of_window = 0
        past = 0

        for li in candidates:
            listing = self._parse_item(
                li=li,
                marketplace=marketplace,
                default_currency=default_currency,
                host=host,
                buying_option=buying_option,
            )
            if not listing:
                continue
            parsed += 1
            # Time-window filter only applies to auctions; BIN listings don't
            # "end" in the relevant sense.
            if buying_option == BuyingOption.AUCTION:
                if listing.end_time > cutoff:
                    out_of_window += 1
                    continue
                if listing.end_time < now:
                    past += 1
                    continue
            results.append(listing)

        log.info(
            "ebay.html.page_parsed",
            marketplace=marketplace.value,
            keyword=keyword,
            page=page,
            html_kb=len(html) // 1024,
            raw_items=len(candidates),
            parsed=parsed,
            kept=len(results),
            out_of_window=out_of_window,
            ended=past,
        )
        self._last_out_of_window = out_of_window

        # One-shot diagnostic: when nothing parsed, save the HTML so we can
        # inspect what eBay actually returned. Removed after we identify the
        # current selector.
        if len(candidates) == 0:
            import os
            from pathlib import Path

            dump_path = Path(f"/tmp/ebay_dump_{marketplace.value}_{keyword}_{page}.html")
            try:
                if not dump_path.exists() or os.environ.get("EBAY_DEBUG_FORCE"):
                    dump_path.write_text(html)
                    log.warning("ebay.html.debug_dump_written", path=str(dump_path))
            except Exception as exc:
                log.warning("ebay.html.debug_dump_failed", error=str(exc))

        return results

    def _parse_item(
        self,
        *,
        li: Tag,
        marketplace: Marketplace,
        default_currency: str,
        host: str,
        buying_option: BuyingOption,
    ) -> Listing | None:
        try:
            # ── item ID (prefer the modern data-listingid attribute) ─────
            ext_id = (li.get("data-listingid") or "").strip() or None

            # ── link ─────────────────────────────────────────────────────
            link = li.select_one("a.s-card__link[href*='/itm/'], a.s-item__link[href*='/itm/']")
            if not link:
                # Some cards have multiple .s-card__link; pick the first with /itm/.
                for a in li.select("a[href*='/itm/']"):
                    link = a
                    break
            if not link or not link.get("href"):
                return None
            raw_url = str(link["href"])
            url = raw_url.split("?")[0]
            if not ext_id:
                ext_id = _extract_item_id(url)
            if not ext_id:
                return None

            # ── title ───────────────────────────────────────────────────
            title_el = li.select_one(".s-card__title, .s-item__title")
            title = _clean_title(title_el.get_text(" ", strip=True) if title_el else "")
            if not title or title.lower() in ("shop on ebay", "neu (sonstige)"):
                return None

            # ── price ───────────────────────────────────────────────────
            price_el = li.select_one(".s-card__price, .s-item__price")
            if not price_el:
                return None
            current_price, currency = _parse_price(
                price_el.get_text(strip=True), default_currency
            )
            if current_price is None:
                return None

            # ── bid count + end time (auctions only) ─────────────────────
            if buying_option == BuyingOption.AUCTION:
                bid_count = _extract_bid_count(li.get_text(" ", strip=True))
                time_el = li.select_one(
                    ".s-card__time, .s-card__caption, .s-item__time-left, .s-item__time-end"
                )
                end_time = _parse_time_left(
                    time_el.get_text(" ", strip=True) if time_el else ""
                )
            else:
                # Buy-It-Now listings don't have bids or end times in the
                # SRP card; set sentinel values the downstream filter ignores.
                bid_count = 0
                end_time = datetime.now(timezone.utc) + timedelta(days=365)

            # ── shipping cost (EUR-normalised, None if not parseable) ────
            shipping = _extract_shipping_eur(
                li.get_text(" ", strip=True), default_currency
            )

            # ── image (prefer data-defer-load; skip the static placeholder) ──
            img_el = li.select_one("img.s-card__image, .s-item__image-img, img")
            image_urls: tuple[str, ...] = ()
            if img_el:
                src = (
                    img_el.get("data-defer-load")
                    or img_el.get("data-src")
                    or img_el.get("src")
                )
                if src and "ebaystatic.com" not in str(src):
                    image_urls = (str(src),)

            return Listing(
                external_id=ext_id,
                marketplace=marketplace,
                title=title,
                description="",
                url=url,  # type: ignore[arg-type]
                current_price=current_price,
                currency=currency,
                current_price_eur=to_eur(current_price, currency),
                bid_count=bid_count,
                end_time=end_time,
                image_urls=image_urls,  # type: ignore[arg-type]
                buying_option=buying_option,
                shipping_cost_eur=shipping,
            )
        except Exception as exc:
            log.debug("ebay.html.parse_skip", error=str(exc))
            return None


# ─── helpers ─────────────────────────────────────────────────────────────
_ITEM_ID_RE = re.compile(r"/itm/(?:[^/]+/)?(\d{10,})")


def _extract_item_id(url: str) -> str | None:
    m = _ITEM_ID_RE.search(url)
    return m.group(1) if m else None


# eBay appends accessibility text like "Wird in neuem Fenster oder Tab geöffnet"
# / "Opens in a new window or tab" to titles. Strip it.
_TITLE_NOISE_RE = re.compile(
    r"\s*(Wird in neuem Fenster oder Tab geöffnet|Opens in a new window or tab|"
    r"Apre una nuova finestra o scheda|S'ouvre dans une nouvelle fenêtre).*$",
    re.IGNORECASE,
)


def _clean_title(title: str) -> str:
    return _TITLE_NOISE_RE.sub("", title).strip()


# Matches "0 Gebote", "1 Gebot", "3 bids", "1 bid", "5 enchères", "2 offerte"
_BID_RE = re.compile(
    r"\b(\d+)\s*(Gebote?|bids?|enchères?|offerte?|puja?s?)\b",
    re.IGNORECASE,
)


def _extract_bid_count(text: str) -> int:
    m = _BID_RE.search(text)
    return int(m.group(1)) if m else 0


# Shipping detection. Free-shipping markers come first because they take
# precedence even when a numeric amount appears elsewhere (e.g. as the price).
_FREE_SHIPPING_RE = re.compile(
    r"(?:kostenlos(?:er)?\s*Versand|kostenfreier?\s*Versand|Gratisversand|"
    r"free\s*(?:postage|shipping|delivery)|livraison\s*gratuite|"
    r"spedizione\s*gratuita|kostenlose\s*Lieferung)",
    re.IGNORECASE,
)
# Seller won't ship — either pickup-only or explicitly excludes Germany.
# We treat both as "ineligible" by returning a sentinel cost that fails any
# reasonable shipping cap.
_NO_SHIPPING_TO_DE_RE = re.compile(
    r"(?:Nur\s*Abholung|Abholung\s*nur|Nur\s*Selbstabholung|"
    r"Versand\s*(?:nicht\s*m[oö]glich|ausgeschlossen)\s*nach\s*Deutschland|"
    r"Keine\s*Lieferung\s*(?:nach|in)\s*Deutschland|"
    r"Verkauf\s*nur\s*an\s*Selbstabholer|"
    r"Pickup\s*only|Local\s*pickup\s*only|"
    r"Does\s*not\s*ship\s*to\s*Germany)",
    re.IGNORECASE,
)
_INELIGIBLE_SHIPPING = Decimal("99999")  # sentinel — guaranteed to fail any cap

# Matches "+EUR 6,19 Lieferung", "+US $4.99 shipping", "+£2.50 postage", etc.
_SHIPPING_COST_RE = re.compile(
    r"\+\s*(EUR|US \$|US\$|\$|£|€|GBP|CHF)\s*([\d.,]+)\s*"
    r"(?:Lieferung|Versand|shipping|postage|delivery|spedizione|livraison)?",
    re.IGNORECASE,
)


def _extract_shipping_eur(text: str, default_currency: str) -> Decimal | None:
    """Best-effort extraction of shipping cost FROM SELLER TO GERMANY.

    eBay.de shows shipping costs to the buyer's default region (Germany on .de),
    so the parsed value is already DE-destination. Returns:
      Decimal("0")           free shipping
      Decimal("99999")       seller won't ship to Germany (pickup-only etc.)
      Decimal(value)         explicit cost, normalised to EUR
      None                   not parseable from card — caller decides whether
                             to allow through
    """
    if _NO_SHIPPING_TO_DE_RE.search(text):
        return _INELIGIBLE_SHIPPING
    if _FREE_SHIPPING_RE.search(text):
        return Decimal("0")
    m = _SHIPPING_COST_RE.search(text)
    if not m:
        return None
    price, currency = _parse_price(f"{m.group(1)} {m.group(2)}", default_currency)
    if price is None:
        return None
    return to_eur(price, currency)


_PRICE_RE = re.compile(r"([£$€]|US \$|EUR|GBP|CHF|JPY)\s*([\d,.]+)")


def _parse_price(text: str, default_currency: str) -> tuple[Decimal | None, str]:
    """Parse 'EUR 1,234.56' or 'US $1,234.56' or '£999.00'."""
    text = text.strip()
    m = _PRICE_RE.search(text)
    if not m:
        return None, default_currency
    symbol, raw = m.group(1).strip(), m.group(2)
    currency = _CURRENCY_SYMBOLS.get(symbol, default_currency)

    # Heuristic for thousands separator. eBay uses "1,234.56" in US/UK
    # and "1.234,56" in DE/FR/IT. Prefer the position of last separator.
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw and raw.count(",") == 1 and len(raw.split(",")[1]) == 2:
        raw = raw.replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", "")

    try:
        return Decimal(raw), currency
    except InvalidOperation:
        return None, currency


# eBay item-page gallery extractor. Looks for the thumbnail strip + main
# image; promotes thumbnails to high-res by swapping `s-l64`/`s-l140` for `s-l1600`.
_THUMB_SIZE_RE = re.compile(r"/s-l\d+(?=\.(jpg|jpeg|png|webp))", re.IGNORECASE)


def _promote_to_high_res(url: str) -> str:
    return _THUMB_SIZE_RE.sub("/s-l1600", url)


def _extract_gallery_images(soup: BeautifulSoup, max_images: int) -> tuple[str, ...]:
    candidates: list[str] = []
    # Modern eBay item page: gallery thumbnails carry the per-photo src.
    for sel in (
        '[data-testid="ux-image-carousel-container"] img',
        ".ux-image-carousel-item img",
        ".ux-image-grid-container img",
        ".ux-image-carousel img",
        "#PicturePanel img",
        ".vi-image-gallery img",
    ):
        for img in soup.select(sel):
            src = (
                img.get("data-zoom-src")
                or img.get("data-src")
                or img.get("src")
            )
            if not src:
                continue
            url = _promote_to_high_res(str(src))
            if "i.ebayimg.com" in url and url not in candidates:
                candidates.append(url)
    return tuple(candidates[:max_images])


# Item-page price extractor. Tries known selectors first, falls back to
# label-based text search ("Aktuelles Gebot" / "Current bid"). Always returns
# the result in EUR (or None if no usable price was found).
_PRICE_LABELS = (
    "Aktuelles Gebot",
    "Aktuelles Höchstgebot",
    "Current bid",
    "Starting bid",
    "Startgebot",
)

_ITEM_PRICE_SELECTORS = (
    '[data-testid="x-price-primary"] .ux-textspans',
    ".x-price-primary .ux-textspans",
    ".x-bin-price__content .ux-textspans",
    ".x-current-bid-value",
    ".x-bid-history__container .ux-textspans",
    'span[itemprop="price"]',
)


# Item-page shipping extractor. eBay shows "Versand: EUR X,XX" / "Shipping: $X.XX"
# in a labelled row near the buy box. We try several known selectors first and
# fall back to label-based text scanning.
_SHIPPING_ITEM_SELECTORS = (
    '[data-testid="ux-labels-values__values-content"] .ux-textspans',
    ".ux-labels-values--shipping .ux-textspans",
    '[data-testid="d-shipping-minview"] .ux-textspans',
    "#shippingSection .ux-textspans",
    "#fshippingCost",
    "#fshippingSummary",
)

_SHIPPING_LABEL_RE = re.compile(
    r"(?:Versand(?:kosten)?|Lieferung|Shipping|Postage|Delivery|"
    r"Spedizione|Livraison)\s*:?\s*([^\n]{1,120})",
    re.IGNORECASE,
)


def _extract_item_page_shipping(
    soup: BeautifulSoup,
    page_text: str,
    default_currency: str,
) -> Decimal | None:
    # 1) Try labelled rows that explicitly carry the shipping cost.
    for sel in _SHIPPING_ITEM_SELECTORS:
        for el in soup.select(sel):
            text = el.get_text(" ", strip=True)
            if not text:
                continue
            value = _shipping_value_from_text(text, default_currency)
            if value is not None:
                return value

    # 2) Fall back to label-based scanning across all visible text.
    for m in _SHIPPING_LABEL_RE.finditer(page_text):
        snippet = m.group(1)
        value = _shipping_value_from_text(snippet, default_currency)
        if value is not None:
            return value
    return None


def _shipping_value_from_text(text: str, default_currency: str) -> Decimal | None:
    """Parse 'EUR 19,90 Standardversand' / 'Free shipping' / '+US $4.99' etc."""
    if _NO_SHIPPING_TO_DE_RE.search(text):
        return _INELIGIBLE_SHIPPING
    if _FREE_SHIPPING_RE.search(text):
        return Decimal("0")
    # Match an explicit currency-symbol price within the snippet.
    m = re.search(
        r"(EUR|US \$|US\$|\$|£|€|GBP|CHF)\s*([\d.,]+)",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None
    price, currency = _parse_price(f"{m.group(1)} {m.group(2)}", default_currency)
    if price is None:
        return None
    return to_eur(price, currency)


def _extract_current_price(soup: BeautifulSoup, default_currency: str) -> Decimal | None:
    # 1) Try known selectors.
    for sel in _ITEM_PRICE_SELECTORS:
        el = soup.select_one(sel)
        if not el:
            continue
        price, currency = _parse_price(el.get_text(" ", strip=True), default_currency)
        if price is not None:
            return to_eur(price, currency)

    # 2) Fall back to scanning text near a recognised label.
    text = soup.get_text(" ", strip=True)
    for label in _PRICE_LABELS:
        i = text.lower().find(label.lower())
        if i < 0:
            continue
        snippet = text[i : i + 250]
        price, currency = _parse_price(snippet, default_currency)
        if price is not None:
            return to_eur(price, currency)
    return None


# Matches "<number> <unit>" pairs in EN ("1d 23h 4m 5s") or DE ("1 Tag 23 Std. 4 Min.")
# or FR/IT abbreviations. Order-independent.
_TIME_PIECE_RE = re.compile(
    r"(\d+)\s*"
    r"(tag(?:e|en)?|tg|std\.?|stunden?|sek\.?|sekunden?|min\.?|minuten?|"
    r"jour(?:s)?|heure(?:s)?|minute(?:s)?|seconde(?:s)?|"
    r"d|h|m|s)\b",
    re.IGNORECASE,
)

_UNIT_TO_SECONDS: dict[str, int] = {
    # days
    "d": 86400, "tag": 86400, "tage": 86400, "tagen": 86400, "tg": 86400,
    "jour": 86400, "jours": 86400,
    # hours
    "h": 3600, "std": 3600, "std.": 3600, "stunde": 3600, "stunden": 3600,
    "heure": 3600, "heures": 3600,
    # minutes
    "m": 60, "min": 60, "min.": 60, "minute": 60, "minuten": 60, "minutes": 60,
    # seconds
    "s": 1, "sek": 1, "sek.": 1, "sekunde": 1, "sekunden": 1,
    "seconde": 1, "secondes": 1,
}


def _parse_time_left(text: str) -> datetime:
    """Parse 'Ends in 1h 23m' or 'Endet in 23 Std. 12 Min.' to an absolute UTC time."""
    now = datetime.now(timezone.utc)
    if not text:
        return now - timedelta(seconds=1)
    total = 0
    found = False
    for m in _TIME_PIECE_RE.finditer(text):
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit not in _UNIT_TO_SECONDS:
            # Strip trailing dot (e.g. "Std." matched as "std" already; this is a safety net).
            unit = unit.rstrip(".")
        seconds = _UNIT_TO_SECONDS.get(unit)
        if seconds is None:
            continue
        total += n * seconds
        found = True
    if not found:
        return now - timedelta(seconds=1)
    return now + timedelta(seconds=total)
