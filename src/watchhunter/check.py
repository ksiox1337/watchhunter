"""`python -m watchhunter check`: test every key and service in one go."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from watchhunter.config.settings import get_settings
from watchhunter.infrastructure.http.client import HttpClient


async def _run() -> int:
    s = get_settings()
    http = HttpClient()
    await http.start()
    results: list[tuple[str, bool, str]] = []

    async def step(name: str, fn: Callable[[], Awaitable[str]]) -> None:
        t = time.monotonic()
        try:
            detail = await fn()
            results.append((name, True, f"{detail} ({time.monotonic() - t:.1f}s)"))
        except Exception as exc:
            results.append((name, False, str(exc)[:160]))

    async def ebay() -> str:
        if not s.ebay_use_api:
            return "HTML mode (EBAY_USE_API=false): no key to test"
        from watchhunter.infrastructure.ebay.client import EbayBrowseClient

        c = EbayBrowseClient(
            client_id=s.ebay_client_id, client_secret=s.ebay_client_secret,
            oauth_url=s.ebay_oauth_url, api_base_url=s.ebay_api_base_url, http=http,
        )
        r = await c.search(marketplace_id=s.ebay_marketplaces[0], query="casio",
                           category_id=None, ends_within_hours=24, limit=1)
        return f"token ok, search total={r.get('total')}"

    async def openai_() -> str:
        from openai import AsyncOpenAI

        c = AsyncOpenAI(api_key=s.openai_api_key, base_url=s.openai_base_url or None)
        await c.models.retrieve(s.openai_model)
        await c.models.retrieve(s.openai_triage_model)
        return f"{s.openai_model}, {s.openai_triage_model} available"

    async def jev() -> str:
        if s.triage_provider.lower() != "jev":
            return "not used (TRIAGE_PROVIDER != jev)"
        url = s.jev_base_url.rsplit("/v1/", 1)[0] + "/v1/models"
        async with http.session.get(url, headers={"Authorization": f"Bearer {s.typesafe_api_key}"}) as r:
            if r.status != 200:
                raise RuntimeError(f"HTTP {r.status}: {(await r.text())[:120]}")
            return "key ok"

    async def telegram() -> str:
        url = f"https://api.telegram.org/bot{s.telegram_bot_token}/getMe"
        async with http.session.get(url) as r:
            body = await r.json(content_type=None)
            if not body.get("ok"):
                raise RuntimeError(str(body.get("description")))
            return f"@{body['result'].get('username')}"

    await asyncio.gather(
        step("eBay", ebay), step("OpenAI", openai_), step("Jev", jev), step("Telegram", telegram)
    )
    await http.close()
    for name, ok, detail in results:
        print(f"{'✓' if ok else '✗'} {name:<9} {detail}")
    return 0 if all(ok for _, ok, _ in results) else 1


def main() -> int:
    return asyncio.run(_run())
