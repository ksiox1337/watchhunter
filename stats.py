"""WatchHunter dashboard. Run anytime — works while the bot is still running.

    python stats.py             # today's stats
    python stats.py --all       # lifetime
    python stats.py --since 1h  # last hour (supports 30m, 6h, 2d)
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB = Path("data/watchhunter.db")
LOG_FILE = Path("logs/watchhunter.log")


# Mirror env settings used to estimate request counts. Defaults match
# what's in .env.example.
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return default
    return [x.strip() for x in raw.split(",") if x.strip()]


AUCTION_KW = len(_env_list("EBAY_KEYWORDS", [""] * 13))
AUCTION_PAGES = _env_int("EBAY_HTML_PAGES_PER_QUERY", 2)
AUCTION_INTERVAL = _env_int("SCAN_INTERVAL_MINUTES", 5)
BIN_KW = len(_env_list("BUY_NOW_KEYWORDS", [""] * 9))
BIN_PAGES = _env_int("BUY_NOW_HTML_PAGES_PER_QUERY", 1)
BIN_INTERVAL = _env_int("BUY_NOW_SCAN_INTERVAL_MINUTES", 1)
BIN_ENABLED = os.environ.get("BUY_NOW_ENABLED", "true").lower() == "true"


def parse_window(spec: str) -> timedelta:
    m = re.fullmatch(r"(\d+)\s*([smhd])", spec.strip().lower())
    if not m:
        raise SystemExit(f"bad --since value: {spec!r} (try 30m, 6h, 2d)")
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(**{"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[unit][:1] + {
        "s": "econds", "m": "inutes", "h": "ours", "d": "ays",
    }[unit])  # ugly but compact


def parse_window_safe(spec: str) -> timedelta:
    m = re.fullmatch(r"(\d+)\s*([smhd])", spec.strip().lower())
    if not m:
        raise SystemExit(f"bad --since value: {spec!r} (try 30m, 6h, 2d)")
    n, unit = int(m.group(1)), m.group(2)
    mapping = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
    return timedelta(**{mapping[unit]: n})


def main() -> None:
    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="lifetime totals")
    g.add_argument("--since", type=str, default=None, help="e.g. 1h, 30m, 2d")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    if not DB.exists():
        print(f"No DB at {DB}. Start the bot first.")
        return

    now = datetime.now(timezone.utc)
    if args.all:
        cutoff = None
        label = "LIFETIME"
    elif args.since:
        cutoff = now - parse_window_safe(args.since)
        label = f"LAST {args.since.upper()}"
    else:
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "TODAY (UTC)"

    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    where = ""
    params: dict[str, str] = {}
    if cutoff is not None:
        where = "WHERE created_at >= :t"
        params["t"] = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    where_listings = where.replace("created_at", "first_seen_at")

    listings = cur.execute(
        f"SELECT COUNT(*) c FROM listings {where_listings}", params
    ).fetchone()["c"]
    evals = cur.execute(
        f"SELECT COUNT(*) c FROM evaluations {where}", params
    ).fetchone()["c"]
    notified = cur.execute(
        f"SELECT COUNT(*) c FROM evaluations {where.replace('created_at', 'notified_at')}",
        params,
    ).fetchone()["c"]

    span = cur.execute(
        f"SELECT MIN(created_at) a, MAX(created_at) b FROM evaluations {where}", params
    ).fetchone()

    rec = cur.execute(
        f"""SELECT recommendation, COUNT(*) c, ROUND(AVG(score),1) avg_s
            FROM evaluations {where}
            GROUP BY recommendation ORDER BY c DESC""",
        params,
    ).fetchall()

    top = cur.execute(
        f"""SELECT l.ebay_item_id, e.brand, e.model, e.score,
                   e.recommendation, e.estimated_market_value_eur,
                   e.current_price_eur, e.potential_profit_eur,
                   e.notified_at IS NOT NULL AS notified
            FROM evaluations e JOIN listings l ON l.id = e.listing_id
            {where.replace('created_at', 'e.created_at')}
            ORDER BY e.score DESC LIMIT {args.top}""",
        params,
    ).fetchall()

    print(f"════════ {label} ════════")
    print(f"Listings persisted        {listings:>5}")
    print(f"Gemini Pro evaluations    {evals:>5}")
    print(f"  └─ pushed to Telegram   {notified:>5}")

    if span["a"] and span["b"]:
        a = datetime.fromisoformat(span["a"])
        b = datetime.fromisoformat(span["b"])
        minutes = max(1, (b - a).total_seconds() / 60)
        print(f"  └─ activity window      {span['a'][:19]} → {span['b'][:19]} "
              f"({minutes:.0f} min)")

        # Estimated HTTP traffic
        a_scans = int(minutes // AUCTION_INTERVAL) + 1
        a_reqs = a_scans * AUCTION_KW * AUCTION_PAGES
        b_scans = (int(minutes // BIN_INTERVAL) + 1) if BIN_ENABLED else 0
        b_reqs = b_scans * BIN_KW * BIN_PAGES
        gallery_reqs = evals
        refresh_reqs = notified
        total = a_reqs + b_reqs + gallery_reqs + refresh_reqs
        rate = total / minutes
        print()
        print(f"══ Estimated HTTP traffic ══")
        print(f"  Auction-scan searches   {a_reqs:>5}  ({a_scans} scans × {AUCTION_KW}kw × {AUCTION_PAGES}p)")
        print(f"  BIN-scan searches       {b_reqs:>5}  ({b_scans} scans × {BIN_KW}kw × {BIN_PAGES}p)")
        print(f"  Gallery fetches         {gallery_reqs:>5}")
        print(f"  Price refreshes         {refresh_reqs:>5}")
        print(f"                          ─────")
        print(f"  TOTAL                   {total:>5}")
        print(f"  Sustained rate          {rate:>4.1f} req/min   (limit: 20)")
        bar_width = min(40, int(rate / 20 * 40))
        bar = "█" * bar_width + "·" * (40 - bar_width)
        print(f"  {bar}  {rate/20*100:.0f}% of ceiling")

    # ── Gemini spend (model-aware, queried from the gemini_usage table) ──
    try:
        usage_rows = cur.execute(
            f"""SELECT model,
                       COUNT(*) calls,
                       COALESCE(SUM(input_tokens),0)  in_tok,
                       COALESCE(SUM(output_tokens),0) out_tok,
                       COALESCE(SUM(cost_usd),0)     cost
                  FROM gemini_usage
                  {where}
                  GROUP BY model
                  ORDER BY cost DESC""",
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        usage_rows = []  # table not created yet (older bot)

    if usage_rows:
        print()
        print("══ Gemini spend (real, from API usage_metadata) ══")
        total_cost = 0.0
        total_calls = 0
        for r in usage_rows:
            cost = float(r["cost"])
            total_cost += cost
            total_calls += int(r["calls"])
            print(
                f"  {r['model']:>22}  {r['calls']:>5} calls  "
                f"in {int(r['in_tok']):>8}  out {int(r['out_tok']):>6}  "
                f"= ${cost:>7.4f}"
            )
        print(f"  {'TOTAL':>22}  {total_calls:>5} calls"
              f"                                = ${total_cost:>7.4f}")

        # Daily / monthly projection from today's data
        if cutoff is not None and span["a"] and span["b"]:
            hours_active = max(0.01, (b - a).total_seconds() / 3600)
            per_hour = total_cost / hours_active
            print()
            print(f"  Activity window:      {hours_active:.1f} hours")
            print(f"  Rate:                 ${per_hour:.4f}/hour")
            print(f"  Projected 24h:        ${per_hour * 24:.2f}/day")
            print(f"  Projected 30 days:    ${per_hour * 24 * 30:.2f}/month")

            cap = float(os.environ.get("MAX_DAILY_COST_USD", "0") or 0)
            if cap > 0:
                pct = total_cost / cap * 100
                bar_w = min(40, int(pct / 100 * 40))
                bar = "█" * bar_w + "·" * (40 - bar_w)
                print()
                print(f"  Cap:                  ${cap:.2f}/day")
                print(f"  Used today:           ${total_cost:.4f}  ({pct:.1f}% of cap)")
                print(f"  {bar}")
                if pct >= 100:
                    print("  ⚠️  CAP REACHED — Gemini calls are being refused")

    print()
    print("══ Recommendation breakdown ══")
    if not rec:
        print("  (no data)")
    for r in rec:
        print(f"  {r['recommendation']:>6}  {r['c']:>4}  avg score {r['avg_s']}")

    print()
    print(f"══ Top {args.top} scored ══")
    if not top:
        print("  (no data)")
    for r in top:
        flag = "📤" if r["notified"] else "  "
        print(f"  {flag} {r['score']:>3} {r['recommendation']:>5}  "
              f"€{r['current_price_eur']:>6} → €{r['estimated_market_value_eur']:>6}  "
              f"profit €{r['potential_profit_eur']:>6}  "
              f"({r['brand'][:18]} {r['model'][:30]})")

    # Quick log check
    if LOG_FILE.exists():
        size_mb = LOG_FILE.stat().st_size / 1024 / 1024
        print()
        print(f"📓 Log file: {LOG_FILE} ({size_mb:.1f} MB)")
        print(f"   Live tail:  tail -f {LOG_FILE}")
        print(f"   Captchas?:  grep ebay.html.debug_dump_written {LOG_FILE}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
