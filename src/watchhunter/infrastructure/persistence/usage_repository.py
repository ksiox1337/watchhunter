"""Repository for Gemini usage rows — feeds the BudgetGuard and stats."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from watchhunter.infrastructure.persistence.database import Database
from watchhunter.infrastructure.persistence.models import GeminiUsageRow


class GeminiUsageRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def record(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Decimal,
    ) -> None:
        async with self._db.session() as session:
            session.add(
                GeminiUsageRow(
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    created_at=datetime.now(timezone.utc),
                )
            )

    async def total_cost_since(self, since: datetime) -> Decimal:
        async with self._db.session() as session:
            row = await session.scalar(
                select(func.coalesce(func.sum(GeminiUsageRow.cost_usd), 0)).where(
                    GeminiUsageRow.created_at >= since
                )
            )
            return Decimal(str(row or 0))

    async def total_cost_today_utc(self) -> Decimal:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return await self.total_cost_since(today_start)

    async def breakdown_since(
        self, since: datetime
    ) -> list[tuple[str, int, int, int, Decimal]]:
        """Return [(model, calls, input_tokens, output_tokens, cost_usd), …]."""
        async with self._db.session() as session:
            rows = (
                await session.execute(
                    select(
                        GeminiUsageRow.model,
                        func.count(GeminiUsageRow.id),
                        func.coalesce(func.sum(GeminiUsageRow.input_tokens), 0),
                        func.coalesce(func.sum(GeminiUsageRow.output_tokens), 0),
                        func.coalesce(func.sum(GeminiUsageRow.cost_usd), 0),
                    )
                    .where(GeminiUsageRow.created_at >= since)
                    .group_by(GeminiUsageRow.model)
                    .order_by(GeminiUsageRow.model)
                )
            ).all()
            return [
                (r[0], int(r[1]), int(r[2]), int(r[3]), Decimal(str(r[4])))
                for r in rows
            ]

    async def total_cost_last_24h(self) -> Decimal:
        return await self.total_cost_since(
            datetime.now(timezone.utc) - timedelta(hours=24)
        )
