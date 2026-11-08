"""Async SQLAlchemy engine + session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from watchhunter.config.logging import get_logger
from watchhunter.infrastructure.persistence.models import Base

log = get_logger(__name__)


class Database:
    """Owns the async engine and session factory; runs `create_all` on startup."""

    def __init__(self, url: str, echo: bool = False) -> None:
        self._engine: AsyncEngine = create_async_engine(url, echo=echo, future=True)
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    async def init(self) -> None:
        """Create tables if they don't exist. MVP-grade migration."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("database.initialized")

    async def close(self) -> None:
        await self._engine.dispose()
        log.info("database.closed")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        session = self._sessionmaker()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker
