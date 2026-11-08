# WatchHunter roadmap

Goal: the best personal deal hunter for collectible watches, built so that the
same engine can later hunt any collectible (cameras, synths, sneakers, cards)
by swapping a "vertical pack" instead of code.

Status on 2026-11-08: eBay Browse API (EBAY_DE), Jev triage (one noul per
listing, batched), gpt-5-mini photo evaluation with a Russian card, Telegram
push. Spend on the first live day: about $0.11 (120 evaluations, most of them
repeats that are now cached), Jev about $0.001.

---

## Where we stand vs. what exists

| | Hosted deal finders (Apify "eBay AI Deal Finder", uBuyFirst) | Open-source monitors (Vinted-Notifications, kleinanzeigen-alert, bargain-eagle) | WatchHunter |
|---|---|---|---|
| New-listing alerts | yes | yes | yes |
| Understands the item from photos | partly (GPT-4o-mini on titles) | no | yes (vision) |
| Value estimate | sold + active comps | no | model memory only ← **main gap** |
| Collector context (story, what to check) | no | no | yes |
| Cost per find | ~$0.024 per deal (Apify) | free | ~$0.002 |
| Learns from your feedback | no | no | no ← **gap** |

Nobody in the open-source space combines vision, comps and a feedback loop.
That is the niche to own.

---

## Phase 1 — Trustworthy value (the one that matters most)

Today the market value is the model's memory. It is often right for famous
references and guessed for the rest.

1. **Active comps from the Browse API (available now).** After evaluation
   identifies brand + model, search the same reference on EBAY_DE/US/UK/FR/IT
   and take the median asking price of comparable listings (same condition
   class, excluding parts lots). Show it next to the model's estimate:
   `Рынок 150–320 € · сейчас на eBay: 12 шт., медиана 189 €`.
2. **Our own sold-price dataset, for free.** Every auction we evaluate ends.
   After `end_time`, read the item once more (`get_item`): the final price is
   a real sale. Store it with the model's estimate. This gives
   - real comps for the next time the same reference shows up;
   - a running accuracy number: median error of our estimate vs. hammer price.
3. **Marketplace Insights API** (sold items, 90 days) is limited release:
   apply for access; switch comps to it once granted.
4. **Value = blend.** Final estimate = weighted blend of own sold history,
   active comps and model memory, weights by how many data points each has.
   The card says which source dominated.

Done when: every card shows a data-backed range, and `stats` reports the
estimate error on ended auctions.

## Phase 2 — Learns from you

5. **Telegram buttons** under each card: 👍 интересно · 👎 мимо · 💰 купил.
   Stored as labels per listing.
6. **Use the labels:** few-shot examples in the triage/eval prompts (your last
   good and bad finds), and automatic tuning of `JEV_THRESHOLD` and
   `MIN_SCORE` to hit a target of N good alerts per day.
7. **Watchlist / snipe reminder:** "напомнить за 10 минут" button; re-checks
   price before the reminder and drops it if it ran past your limit.

## Phase 3 — More supply

8. **More eBay sites** with one query each: EBAY_US, EBAY_GB, EBAY_FR,
   EBAY_IT, EBAY_NL. Cross-border price gaps are where vintage digitals are
   cheapest. Quota stays well under 5000/day with OR-grouped queries.
9. **Catawiki and Chrono24** (watch-specific). No public APIs: start with
   saved-search e-mails or RSS where offered; scraping only with strict pacing
   (the eBay HTML ban is the lesson).
10. **Kleinanzeigen / Vinted** through the same paced adapter; fixed price,
    fresh-only.
11. **eBay Feed API** (limited release, hourly change files) if new-listing
    latency ever matters more than it does with the 60 s poll.

## Phase 4 — Not only watches ("vertical packs")

12. Move everything watch-specific into `verticals/watches/`:
    triage criteria, evaluation prompt, keywords, categories, card wording.
    A new vertical = a new folder (cameras: Leica/Contax; synths; Game Boy).
13. One process runs several packs; each has its own Telegram topic/thread.

## Phase 5 — Runs like a product

14. **Persistence:** store rejected evaluations too (today only in memory, so a
    restart re-evaluates once); Postgres option for multi-user.
15. **Deploy:** Dockerfile + compose, small VPS (Hetzner CX22) or Fly.io;
    the laptop and SSD stop being the server.
16. **Observability:** `/stats` in Telegram (finds, spend, quota left,
    estimate error), daily digest, `python -m watchhunter check` that tests
    eBay, OpenAI, Jev and Telegram keys in one go.
17. **Benchmark** (as in grid-storm-sensors `bench/`): a labelled set of past
    listings; report triage recall, valuation error and cost per good find for
    every model/prompt change, as an HTML report.
18. **Showcase README:** plain explanation, architecture diagram, a real card
    screenshot, honest numbers from the benchmark.

---

## Weak spots found in the code (to fix along the way)

| Issue | Effect | Fix |
|---|---|---|
| Value from model memory | wrong estimates on obscure references | Phase 1 |
| Rejections only in memory | one re-evaluation per restart | store a `rejected` row (14) |
| Scheduler jobs overlap with long scans | `skipped: maximum number of running instances` | per-job timeouts, shorter BIN pages |
| HTML eBay adapter still default when API keys missing | IP bans | keep only as explicit opt-in |
| `gemini_usage` table name | confusing | rename to `llm_usage` with a migration |
| Old README describes Gemini / old pipeline | wrong for showcase | rewrite (18) |
| Valuation prompt is watch-only and long | not reusable | verticals (12) |

## Suggested order

1 → 2 → 16 (`check`, `/stats`) → 5–6 → 8 → 14–15 → 12–13 → 17–18.
Phase 1 first: a deal hunter is only as good as its value estimate.

## Sources

- Hosted deal finders: [Apify eBay AI Deal Finder](https://apify.com/webdatalabs/ebay-deal-finder), [uBuyFirst](https://ubuyfirst.com/ebay-bots/)
- Open source: [Vinted-Notifications](https://github.com/Fuyucch1/Vinted-Notifications), [kleinanzeigen-alert](https://pkg.go.dev/github.com/danielstefank/kleinanzeigen-alert), [bargain-eagle](https://awesome.ecosyste.ms/api/v1/projects/github.com%2Feightsq%2Fbargain-eagle)
- eBay data: [Marketplace Insights API](https://developer.ebay.com/api-docs/buy/marketplace-insights/overview.html) (sold items, limited release), [Buy APIs overview incl. Feed API](https://developer.ebay.com/api-docs/buy/static/buy-landing.html)
- Watch prices: [WatchCharts](https://marketplace.watchcharts.com/subscribe) (no public API), Chrono24 has no public sold-price archive
