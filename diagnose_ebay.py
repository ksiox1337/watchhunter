"""One-off: fetch an ebay.de search page and report what selectors are present.

Run from the project root:
    python diagnose_ebay.py
"""

from __future__ import annotations

import asyncio
from collections import Counter

import aiohttp
from bs4 import BeautifulSoup

URL = (
    "https://www.ebay.de/sch/i.html"
    "?_nkw=armbanduhr&LH_Auction=1&LH_HasBids=1&_sop=1&_udhi=80"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
}

OUT = "/tmp/ebay_sample.html"


async def fetch() -> None:
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.get(URL) as r:
            text = await r.text()
            with open(OUT, "w") as f:
                f.write(text)
            print(f"saved {len(text):,} bytes  status={r.status}  -> {OUT}")


def inspect() -> None:
    soup = BeautifulSoup(open(OUT).read(), "lxml")

    print("\n── Top tag counts ──")
    tag_counts = Counter(el.name for el in soup.find_all(True))
    for tag in ("li", "article", "div", "section"):
        print(f"  {tag:8}  {tag_counts.get(tag, 0)}")

    print("\n── Top item-related classes ──")
    classes: Counter[str] = Counter()
    for el in soup.find_all(True):
        for c in (el.get("class") or []):
            if any(k in c.lower() for k in ("item", "srp", "card", "list", "result")):
                classes[c] += 1
    for c, n in classes.most_common(30):
        print(f"  {n:4}  {c}")

    print("\n── Top data-* attrs on <li>/<div>/<article> ──")
    data_attrs: Counter[str] = Counter()
    for el in soup.find_all(["li", "div", "article"]):
        for attr in el.attrs:
            if attr.startswith("data-") and attr in (
                "data-viewport-id",
                "data-listingid",
                "data-itemid",
                "data-view",
                "data-marko-key",
            ):
                data_attrs[attr] += 1
    for a, n in data_attrs.most_common(20):
        print(f"  {n:4}  {a}")

    print("\n── First few item-link <a> hrefs ──")
    seen = 0
    for a in soup.select("a[href*='/itm/']"):
        href = a.get("href", "").split("?")[0]
        if href and seen < 5:
            print(f"  {href}")
            seen += 1


async def main() -> None:
    await fetch()
    inspect()


if __name__ == "__main__":
    asyncio.run(main())
