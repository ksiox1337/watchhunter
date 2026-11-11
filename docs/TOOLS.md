# Tools that can make WatchHunter better (research, 2026-11-08)

The weak spot is the same everywhere: value and rarity come from the model's
memory. Everything below is judged by one question: does it give us real
sale data, a better identification, or a better filter for what you like?

## Use — high impact, low cost

| # | Tool | What it gives | Cost / risk | Status |
|---|---|---|---|---|
| 1 | **Own sale history** (eBay Browse API, already connected) | Every auction we evaluated ends. Poll it in its last minutes (price + bid count); the last snapshot is close to the hammer price. Over weeks this becomes our own "sold" database per reference: real rarity (how many per 90 days) and real value. Also measures how wrong the model's estimate was. | Free, inside the 5,000 calls/day quota. `getItem` on an already ended item is not reliable, so snapshot before the end. | build |
| 2 | **eBay Marketplace Insights API** | Official sold items, last 90 days, by keyword/category. Exactly what rarity and value need. | Free but limited release: apply via developer.ebay.com, approval not guaranteed. | apply now |
| 3 | **OpenAI `web_search` tool, finds only** | For the few listings that pass (5–15/day): look up sold prices / references before the card is written; cite the source in the card. | ~$0.01 per search call + tokens → ~$0.05–0.20/day. Only on finds, never on every listing. | try behind a flag |
| 4 | **Perceptual image hash** (`imagehash`, local) | Same photo seen before → relisting, stock photo, or the same watch on eBay and Kleinanzeigen. Free dedup across sources; flags scams that reuse photos. | Free, a few ms per image. | build |
| 5 | **Rarity / value benchmark** (pattern from grid-storm-sensors `bench/report.py`) | Already started (`bench/rarity_bench.py`). Add an HTML report and a value check against #1 once sales accumulate. | Free (~$0.06 per run). | extend |

## From your own repositories

| Repo | What to reuse | Where it helps |
|---|---|---|
| **grid-storm-sensors** | Jev `choice` with criteria + calibrated probabilities; `check` command for keys; bench HTML report; "honest results" README | rarity benchmark (done), `python -m watchhunter check`, showcase README |
| **MetaVerb / BanditAffect** | Contextual neural bandit (Thompson-style exploration) | Learn from 👍/👎 buttons which alerts you want: features = brand, rarity, era, price, profit, source. Explores a little so it doesn't lock into one brand. |
| **ehl-finale-template** (swarm + lean browsing) | Model-driven Playwright browsing over CDP, re-login, paced requests | Sources without an API: Catawiki watch auctions, Chrono24 listings. One browser, slow pace. |
| **lingobot-obsidian-sync** | Obsidian plugin that syncs bot data into notes | "Collection journal": every find you mark 💰 becomes a note with photos, price paid, story. |
| **lora-exercise-predictor** | LoRA fine-tune + serving | Later, after ~500 labelled finds: a small tuned model for triage/rarity instead of prompts. |
| **SaveForRecovery** | Telegram inline menus, i18n | Buttons under cards (👍 / 👎 / 💰 / remind me), language switch. |

## Looked at, not recommended (now)

| Tool | Why not |
|---|---|
| WorthPoint | Big sold archive (740M+ prices) but no public API; subscription, manual only. |
| Terapeak (eBay) | Free 3 years of sold data, but UI only; no API for regular developers. Manual check of a find is fine. |
| WatchCharts | No public API; luxury references, little vintage-digital coverage. |
| 130point | Sold eBay data mainly for trading cards; no documented API. |
| Apify eBay sold-items scrapers | Paid per result and against eBay terms; only if #2 is refused. |
| SerpApi / Google Lens reverse image | Works for identifying a watch from a photo, but paid ($50+/month) and Google is suing SerpApi. #4 covers the duplicate-photo case for free. |

## Suggested order

1 (own sale history) → 2 (apply today) → 4 (image hash) → buttons + bandit →
3 (web search on finds, A/B against the benchmark) → Catawiki via browser agent.

## Sources

- eBay sold data: [Marketplace Insights API](https://developer.ebay.com/api-docs/buy/marketplace-insights/overview.html), [Terapeak has no API (eBay community)](https://community.ebay.com/t5/Traditional-APIs-Search/Get-data-of-terapeak-research-using-API/m-p/34521356/highlight/true), [Terapeak free for sellers](https://www.valueaddedresource.net/ebay-makes-terapeak)
- WorthPoint: [review 2026](https://underpricedai.com/blog/is-worthpoint-worth-the-price-honest-review-from-a-reseller-in-2026), [about](https://ww.worthpoint.com/about)
- OpenAI web search pricing: [aitoolsatlas](https://aitoolsatlas.ai/tools/openai-responses-api/pricing), [pricing change](https://pricingsaas.com/companies/openai.api/diffs/2026W14)
- Reverse image: [SerpApi pricing](https://scrapegraphai.com/blog/serpapi-pricing), [Google v. SerpApi](https://usagepricing.com/blueprint/activity/2025-12-19-serpapi-google-lawsuit)
- Watch data: [WatchCharts](https://marketplace.watchcharts.com/subscribe)
