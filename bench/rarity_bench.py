"""Rarity benchmark: does the classifier put real listings in the right tier?

Builds a set of live eBay listings for references with a known rarity tier
(bench/rarity_refs.json), all prices, auctions and Buy It Now, EBAY_DE + EBAY_US,
then runs one or more classifiers on the same set and prints accuracy and a
confusion matrix.

  .venv/bin/python bench/rarity_bench.py fetch            # build/refresh the set
  .venv/bin/python bench/rarity_bench.py run mini jev     # classify + report

The set is cached in bench/out/rarity_set.json (git-ignored scenario data).
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from watchhunter.config.settings import Settings
from watchhunter.container import build_container
from watchhunter.domain.models import Marketplace
from watchhunter.infrastructure.ebay.mappers import parse_summary

ROOT = Path(__file__).parent
SET = ROOT / "out" / "rarity_set.json"
TIERS = ["low", "medium", "high", "very_high"]
MARKETS = [("EBAY_DE", "260324"), ("EBAY_US", "31387")]
PER_REF = 6


def _tier(t: str) -> str:
    return "high" if t == "very_high" else t  # benchmark uses 3 tiers


async def fetch() -> None:
    spec = json.loads((ROOT / "rarity_refs.json").read_text())
    refs, exclude_all = spec["refs"], spec.get("exclude_all", [])
    c = await build_container(Settings())
    client = c.marketplace._client  # Browse API client
    items = []
    try:
        for ref in refs:
            got = []
            for market, cat in MARKETS:
                payload = await client.search(
                    marketplace_id=market, query=ref["query"], category_id=cat,
                    ends_within_hours=24 * 30, limit=50, fixed_price=False,
                )
                bin_payload = await client.search(
                    marketplace_id=market, query=ref["query"], category_id=cat,
                    ends_within_hours=0, limit=50, fixed_price=True,
                )
                for raw in (payload.get("itemSummaries") or []) + (bin_payload.get("itemSummaries") or []):
                    t = (raw.get("title") or "").lower()
                    if not any(m in t for m in ref["must"]):
                        continue
                    if any(x in t for x in ref.get("exclude", []) + exclude_all):
                        continue
                    lst = parse_summary(raw, Marketplace(market))
                    if lst and lst.image_urls and all(g["external_id"] != lst.external_id for g in got):
                        got.append({"tier": ref["tier"], "query": ref["query"], **json.loads(lst.model_dump_json())})
            # spread across price: cheapest, priciest and between
            got.sort(key=lambda g: float(g["current_price_eur"]))
            if len(got) > PER_REF:
                step = (len(got) - 1) / (PER_REF - 1)
                got = [got[round(i * step)] for i in range(PER_REF)]
            print(f"{ref['query']:<20} {ref['tier']:<7} {len(got)}")
            items += got
    finally:
        await c.aclose()
    SET.write_text(json.dumps(items, indent=1, ensure_ascii=False))
    print(f"saved {len(items)} listings -> {SET}")


RARITY_CRITERIA = {
    "low": "Still in production or made in huge numbers; always for sale (e.g. Casio F-91W, A168, current G-Shock)",
    "medium": "Discontinued vintage reference that turns up for sale every week or two (e.g. common 1970s Seiko 5, Seiko 6309 diver)",
    "high": "Scarce vintage reference, a few listings per month worldwide (e.g. Seiko 0674 LC, Pulsar P2 LED, Casio CA-90)",
    "very_high": "Grail: prototype, limited edition or unused-in-box rare reference, about once a year",
}


def _openai(c):
    a = c.analyzer
    return getattr(a, "_evaluator", a)


async def classify(name: str, c, listing) -> str:
    if name == "mini":  # current production path: the vision verdict's rarity
        from watchhunter.infrastructure.llm.prompts import build_user_prompt  # noqa: PLC0415

        a = _openai(c)
        urls = [str(u) for u in listing.image_urls][:4]
        text = build_user_prompt(
            title=listing.title, description=listing.description,
            current_price_eur=f"{listing.current_price_eur:.2f}",
            original_price=f"{listing.current_price:.2f}", original_currency=listing.currency,
            bid_count=listing.bid_count, hours_left=listing.hours_until_end, has_images=bool(urls),
        )
        v = await a._with_image_fallback(lambda u: a._evaluate_call(text, u, mode="verdict"), urls)
        return str(v.get("rarity"))
    if name == "jev":  # TypeSafe Jev choice over the four tiers, title + description only
        jev = c.analyzer
        body = {
            "model": jev._model,
            "state": f"Watch listing title: {listing.title}\nDescription: {(listing.description or '')[:300]}",
            "questions": {"rarity": {
                "type": "choice",
                "instructions": "How rare is the watch reference in this listing among collectors (how often does the ORIGINAL reference turn up for sale)?",
                "criteria": RARITY_CRITERIA,
            }},
        }
        r = await jev._post(body)
        return str(r["answers"]["rarity"]["choice"])
    raise ValueError(name)


async def run(names: list[str]) -> None:
    from watchhunter.domain.models import Listing

    items = json.loads(SET.read_text())
    c = await build_container(Settings())
    sem = asyncio.Semaphore(6)
    try:
        for name in names:
            async def one(it):
                async with sem:
                    lst = Listing.model_validate({k: v for k, v in it.items() if k not in ("tier", "query")})
                    try:
                        return await classify(name, c, lst)
                    except Exception as exc:  # report, don't stop the benchmark
                        return f"error:{str(exc)[:60]}"
            preds = await asyncio.gather(*(one(it) for it in items))
            report(name, items, preds)
    finally:
        await c.aclose()


def report(name: str, items: list[dict], preds: list[str]) -> None:
    conf: dict[str, Counter] = defaultdict(Counter)
    ok = 0
    by_ref: dict[str, Counter] = defaultdict(Counter)
    for it, p in zip(items, preds, strict=True):
        p3 = _tier(p) if p in TIERS else "err"
        conf[it["tier"]][p3] += 1
        by_ref[it["query"]][p3] += 1
        ok += p3 == it["tier"]
    rare_true = sum(1 for it in items if it["tier"] == "high")
    rare_hit = conf["high"]["high"]
    rare_pred = sum(conf[t]["high"] for t in conf)
    lines = [
        f"\n## {name}: accuracy {ok}/{len(items)} = {ok / len(items):.0%}",
        f"rare recall {rare_hit}/{rare_true}, rare precision {rare_hit}/{rare_pred or 1}",
        "expected \\ predicted   low  medium  high  err",
    ]
    for t in ("low", "medium", "high"):
        row = conf[t]
        lines.append(f"{t:<22} {row['low']:>4} {row['medium']:>7} {row['high']:>5} {row['err']:>4}")
    lines.append("per reference:")
    for q, cnt in by_ref.items():
        lines.append(f"  {q:<20} " + " ".join(f"{k}:{v}" for k, v in sorted(cnt.items())))
    text = "\n".join(lines)
    (ROOT / "out" / f"rarity_{name}_preds.json").write_text(json.dumps(preds))
    print(text)
    (ROOT / "out" / f"rarity_{name}.md").write_text(text)


if __name__ == "__main__":
    cmd = sys.argv[1]
    asyncio.run(fetch() if cmd == "fetch" else run(sys.argv[2:]))
