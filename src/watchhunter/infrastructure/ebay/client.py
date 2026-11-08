"""eBay Browse API client with OAuth2 client-credentials flow."""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

import aiohttp
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from watchhunter.config.logging import get_logger
from watchhunter.domain.exceptions import MarketplaceError
from watchhunter.infrastructure.http.client import HttpClient

log = get_logger(__name__)


class EbayBrowseClient:
    """Thin async wrapper around the eBay Browse API."""

    SCOPE = "https://api.ebay.com/oauth/api_scope"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        oauth_url: str,
        api_base_url: str,
        http: HttpClient,
    ) -> None:
        if not client_id or not client_secret:
            raise MarketplaceError("eBay client_id/client_secret are required for the API adapter")
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth_url = oauth_url
        self._api_base = api_base_url.rstrip("/")
        self._http = http
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    # ─── OAuth ────────────────────────────────────────────────────────────
    async def _ensure_token(self) -> str:
        async with self._token_lock:
            now = time.time()
            if self._token and now < self._token_expires_at - 30:
                return self._token

            basic = base64.b64encode(
                f"{self._client_id}:{self._client_secret}".encode()
            ).decode()
            headers = {
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            }
            data = {"grant_type": "client_credentials", "scope": self.SCOPE}

            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(min=1, max=10),
                retry=retry_if_exception_type(aiohttp.ClientError),
                reraise=True,
            ):
                with attempt:
                    async with self._http.session.post(
                        self._oauth_url, data=data, headers=headers
                    ) as resp:
                        if resp.status != 200:
                            body = await resp.text()
                            raise MarketplaceError(
                                f"eBay OAuth failed (status {resp.status}): {body[:200]}"
                            )
                        payload = await resp.json()

            self._token = payload["access_token"]
            self._token_expires_at = now + int(payload.get("expires_in", 7200))
            log.info("ebay.oauth.refreshed", expires_in=payload.get("expires_in"))
            return self._token  # type: ignore[return-value]

    # ─── Search ───────────────────────────────────────────────────────────
    async def search(
        self,
        *,
        marketplace_id: str,
        query: str,
        category_id: str | None,
        ends_within_hours: int,
        max_price: float | None = None,
        price_currency: str = "EUR",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Call /buy/browse/v1/item_summary/search with auction-only filter."""
        token = await self._ensure_token()

        # See https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
        filters = [
            "buyingOptions:{AUCTION}",
            f"itemEndDate:[..{_iso_offset(ends_within_hours)}]",
        ]
        if max_price is not None:
            filters.append(f"price:[..{max_price}]")
            filters.append(f"priceCurrency:{price_currency}")
        params: dict[str, str | int] = {
            "q": query,
            "limit": min(limit, 200),
            "offset": offset,
            "filter": ",".join(filters),
            "sort": "endingSoonest",
        }
        if category_id:
            params["category_ids"] = category_id

        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
            "Accept": "application/json",
        }

        url = f"{self._api_base}/buy/browse/v1/item_summary/search"

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(min=1, max=10),
            retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
            reraise=True,
        ):
            with attempt:
                async with self._http.session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 401:
                        # Token revoked; clear and retry once.
                        self._token = None
                        raise aiohttp.ClientError("eBay 401, refreshing token")
                    if resp.status >= 400:
                        body = await resp.text()
                        raise MarketplaceError(
                            f"eBay search failed (status {resp.status}): {body[:200]}"
                        )
                    return await resp.json()  # type: ignore[no-any-return]
        raise MarketplaceError("eBay search exhausted retries")

    async def get_item(self, item_id: str, marketplace_id: str) -> dict[str, Any]:
        """Fetch the full detail for a single item (more images, description)."""
        token = await self._ensure_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
            "Accept": "application/json",
        }
        url = f"{self._api_base}/buy/browse/v1/item/{item_id}"
        async with self._http.session.get(url, headers=headers) as resp:
            if resp.status >= 400:
                body = await resp.text()
                raise MarketplaceError(
                    f"eBay item lookup failed (status {resp.status}): {body[:200]}"
                )
            return await resp.json()  # type: ignore[no-any-return]


def _iso_offset(hours: int) -> str:
    """Return an ISO 8601 UTC timestamp `hours` from now (used in the filter)."""
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
