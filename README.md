# WatchHunter

Automated scanner that hunts for **undervalued watches** on eBay auctions ending within the next 24 hours, evaluates each candidate with **Gemini** (acting as a watch dealer/auction expert with multimodal vision), persists promising hits in **SQLite**, and pushes them to **Telegram** every hour.

```
eBay (API or HTML)  ─┐
                     ├─►  ListingFilter  ─►  Gemini multimodal eval  ─►  SQLite  ─►  Telegram
Scheduler (APS)   ──┘                                                              (hourly)
```

## Features

- **Two eBay adapters, hot-swappable**: official Browse API (when you have credentials) and an HTML fallback (no keys required for development).
- Searches `Watches` (US: 31387) and `Armbanduhren` (DE: 260324) — plus any other marketplace/category you configure.
- Filters auctions to **bidded + ending within 24h** before LLM cost is incurred.
- Gemini returns **structured JSON** validated through Pydantic into a `WatchEvaluation`.
- Discards anything with `score < 60` or `recommendation == "skip"`.
- Telegram notifications include photo, price, estimated value, profit, end time, link, and Gemini's reasoning.
- Clean Architecture: `domain` → `application` → `infrastructure` → `presentation`. Ports & adapters make it trivial to add Chrono24, OpenAI, Discord, or Postgres later.
- Async-first (`asyncio` / `aiohttp` / `aiosqlite`), with retry (`tenacity`) and rate-limiting (`aiolimiter`) on every external call.

---

## Project layout

```
src/watchhunter/
├── config/             Settings (Pydantic) + structlog setup
├── domain/             Listing, WatchEvaluation, exceptions  (pure)
├── application/
│   ├── ports/          MarketplacePort, AnalyzerPort, NotifierPort, ListingRepository
│   ├── services/       ListingFilter, DealEvaluator
│   └── use_cases/      ScanWatchesUseCase, NotifyPromisingUseCase
├── infrastructure/
│   ├── http/           shared aiohttp session
│   ├── ratelimit/      aiolimiter wrapper
│   ├── ebay/           Browse API + HTML fallback adapters
│   ├── gemini/         multimodal client + JSON-schema-validated adapter
│   ├── telegram/       Bot API client + adapter
│   └── persistence/    SQLAlchemy 2.0 async engine, ORM, repository
├── scheduler/          APScheduler (scan every 15m, notify every 60m)
├── container.py        DI composition root
└── main.py             Entry point (asyncio.run + signal handling)
```

---

## Database schema

Two tables:

- **`listings`** — every unique auction (dedup key: `ebay_item_id`)
- **`evaluations`** — one row per Gemini analysis, FK to `listings`

See `src/watchhunter/infrastructure/persistence/models.py`.

---

## Setup

### Prerequisites

- **Python 3.12+**
- A **Gemini API key** — get one at https://aistudio.google.com/apikey (free tier OK for testing)
- A **Telegram bot** — create one via `@BotFather`, then send a message to your bot and grab the chat ID
- *(Optional)* **eBay developer account** — https://developer.ebay.com — for production-grade access

### 1. Create venv and install dependencies

```bash
cd watchhunter
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
# dev extras (tests, ruff, mypy):
pip install -r requirements-dev.txt
pip install -e .
```

### 2. Configure environment

```bash
cp .env.example .env
# then edit .env and set at minimum:
#   GEMINI_API_KEY
#   TELEGRAM_BOT_TOKEN
#   TELEGRAM_CHAT_ID
# Leave EBAY_USE_API=false until you have eBay credentials — the HTML adapter will be used.
```

### 3. Run

```bash
python -m watchhunter
```

You should see structured JSON logs like:

```json
{"event": "app.starting", "level": "info", "version": "0.1.0", ...}
{"event": "container.marketplace", "impl": "ebay.html_fallback", ...}
{"event": "database.initialized", ...}
{"event": "scheduler.started", "scan_interval_min": 15, "notify_interval_min": 60}
{"event": "scan.complete", "fetched": 47, "analyzed": 12, "promising": 3, ...}
```

For local development with pretty logs, set `LOG_JSON=false`.

### 4. Run tests

```bash
pytest
```

---

## Switching from HTML to API

When you obtain eBay credentials:

```bash
# in .env
EBAY_USE_API=true
EBAY_CLIENT_ID=your_id_here
EBAY_CLIENT_SECRET=your_secret_here
```

Restart the app — `container.py` picks the API adapter automatically. No code changes needed.

---

## Extending to other marketplaces

1. Implement `MarketplacePort` in `infrastructure/<marketplace>/adapter.py`.
2. Add a factory in `container._build_marketplace`.
3. Done. The use cases don't change.

The same applies to `AnalyzerPort` (swap Gemini for OpenAI/Claude) and `NotifierPort` (swap Telegram for Slack/Discord/email).

---

## Configuration reference

All settings live in `.env` and are validated at startup via Pydantic. See `.env.example` for the full list with comments. Key knobs:

| Variable | Default | Meaning |
|---|---|---|
| `SCAN_INTERVAL_MINUTES` | 15 | How often to scan eBay |
| `NOTIFY_INTERVAL_MINUTES` | 60 | How often to push to Telegram |
| `MIN_SCORE` | 60 | Discard evaluations below this score |
| `AUCTION_ENDS_WITHIN_HOURS` | 24 | Auction time window |
| `REANALYSIS_TTL_HOURS` | 6 | Don't re-call Gemini for the same listing within this window |
| `GEMINI_RATE_LIMIT_RPM` | 5 | Per the free tier of `gemini-2.5-pro` |
| `EBAY_MARKETPLACES` | `EBAY_US,EBAY_DE` | Comma-separated |
| `EBAY_CATEGORY_IDS` | `31387,260324` | Wristwatches / Armbanduhren |

---

## Error handling strategy

- All adapter exceptions inherit from `DomainError` (`MarketplaceError`, `AnalyzerError`, `NotifierError`).
- Scheduler jobs are wrapped in `_safe_*` methods — a single failed run never crashes the loop.
- `tenacity` retries every external HTTP call with exponential backoff (3 attempts, 1–20 s).
- The use cases collect per-listing exceptions into a stats dict rather than aborting the whole scan.

---

## Operational notes

- **State is local** — the SQLite file lives at `./data/watchhunter.db`. Back it up if you care about history.
- **Cost control**: `ListingFilter` cuts the candidate list before LLM calls; `REANALYSIS_TTL_HOURS` prevents re-spending on the same listing.
- **Telegram caption limit** is 1024 chars — the adapter truncates safely.
- **HTML adapter caveat**: best-effort, brittle, against eBay ToS for production. Use the API adapter once you have keys.

---

## Roadmap (future work)

- Replace static FX table with a live FX adapter.
- Add a `cleanup` job that deletes expired auctions older than N days.
- Add Postgres support (just swap `DATABASE_URL`).
- Inline buttons in Telegram (mark as "interested" / "bid placed").
- Live FX + per-marketplace shipping cost adjustment in the prompt.
