"""Shared aiohttp session with sensible defaults and lifecycle management."""

from __future__ import annotations

import asyncio
from typing import Self

import aiohttp


class HttpClient:
    """Wraps a long-lived aiohttp.ClientSession.

    Use as `async with HttpClient() as client:` or call `start()` / `close()`
    explicitly when sharing across a long-running app.
    """

    def __init__(
        self,
        *,
        total_timeout_s: float = 30.0,
        connect_timeout_s: float = 10.0,
        user_agent: str = "WatchHunter/0.1 (+https://github.com/)",
        max_connections: int = 100,
    ) -> None:
        self._timeout = aiohttp.ClientTimeout(
            total=total_timeout_s, connect=connect_timeout_s
        )
        self._user_agent = user_agent
        self._max_connections = max_connections
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._session is None or self._session.closed:
                connector = aiohttp.TCPConnector(limit=self._max_connections)
                self._session = aiohttp.ClientSession(
                    timeout=self._timeout,
                    connector=connector,
                    headers={"User-Agent": self._user_agent},
                )

    async def close(self) -> None:
        async with self._lock:
            if self._session is not None and not self._session.closed:
                await self._session.close()
            self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            raise RuntimeError("HttpClient is not started. Call `await client.start()` first.")
        return self._session

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
