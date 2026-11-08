"""APScheduler wiring."""

from __future__ import annotations

from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from watchhunter.application.use_cases.notify_promising import NotifyPromisingUseCase
from watchhunter.application.use_cases.scan_watches import ScanWatchesUseCase
from watchhunter.config.logging import get_logger

log = get_logger(__name__)


class Scheduler:
    def __init__(
        self,
        *,
        scan_use_case: ScanWatchesUseCase,
        notify_use_case: NotifyPromisingUseCase,
        scan_interval_minutes: int,
        notify_interval_minutes: int,
        buy_now_use_case: ScanWatchesUseCase | None = None,
        buy_now_interval_minutes: int = 1,
        buy_now_interval_seconds: int = 0,
        kleinanzeigen_use_case: ScanWatchesUseCase | None = None,
        kleinanzeigen_interval_seconds: int = 60,
        extra_jobs: list[tuple[str, Any, int]] | None = None,
    ) -> None:
        self._scan = scan_use_case
        self._notify = notify_use_case
        self._buy_now = buy_now_use_case
        self._kleinanzeigen = kleinanzeigen_use_case
        self._scan_interval = scan_interval_minutes
        self._notify_interval = notify_interval_minutes
        self._buy_now_interval = buy_now_interval_minutes
        self._buy_now_interval_seconds = buy_now_interval_seconds
        self._kleinanzeigen_interval_seconds = kleinanzeigen_interval_seconds
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        # (name, async callable, interval seconds): sale tracker, Telegram updates.
        self._extra_jobs = extra_jobs or []

    def start(self) -> None:
        self._scheduler.add_job(
            self._safe_scan,
            trigger=IntervalTrigger(minutes=self._scan_interval),
            id="scan_watches",
            name="scan_watches",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            next_run_time=_now_plus_seconds(5),
        )
        self._scheduler.add_job(
            self._safe_notify,
            trigger=IntervalTrigger(minutes=self._notify_interval),
            id="notify_promising",
            name="notify_promising",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
            next_run_time=_now_plus_seconds(60),
        )
        if self._buy_now is not None:
            if self._buy_now_interval_seconds > 0:
                buy_now_trigger = IntervalTrigger(
                    seconds=self._buy_now_interval_seconds
                )
                buy_now_cadence_label = f"{self._buy_now_interval_seconds}s"
            else:
                buy_now_trigger = IntervalTrigger(minutes=self._buy_now_interval)
                buy_now_cadence_label = f"{self._buy_now_interval}min"
            self._scheduler.add_job(
                self._safe_buy_now_scan,
                trigger=buy_now_trigger,
                id="buy_now_scan",
                name="buy_now_scan",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
                next_run_time=_now_plus_seconds(15),
            )
        else:
            buy_now_cadence_label = None

        if self._kleinanzeigen is not None:
            self._scheduler.add_job(
                self._safe_kleinanzeigen_scan,
                trigger=IntervalTrigger(
                    seconds=self._kleinanzeigen_interval_seconds
                ),
                id="kleinanzeigen_scan",
                name="kleinanzeigen_scan",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
                next_run_time=_now_plus_seconds(25),
            )
            ka_cadence_label = f"{self._kleinanzeigen_interval_seconds}s"
        else:
            ka_cadence_label = None

        for name, job, seconds in self._extra_jobs:
            self._scheduler.add_job(
                _safe(name, job),
                trigger=IntervalTrigger(seconds=seconds),
                id=name,
                name=name,
                max_instances=1,
                coalesce=True,
                replace_existing=True,
                next_run_time=_now_plus_seconds(20),
            )

        self._scheduler.start()
        log.info(
            "scheduler.started",
            scan_interval_min=self._scan_interval,
            notify_interval_min=self._notify_interval,
            buy_now_cadence=buy_now_cadence_label,
            kleinanzeigen_cadence=ka_cadence_label,
        )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")

    async def _safe_scan(self) -> None:
        try:
            await self._scan.execute()
        except Exception as exc:
            log.exception("scheduler.scan_failed", error=str(exc))

    async def _safe_notify(self) -> None:
        try:
            await self._notify.execute()
        except Exception as exc:
            log.exception("scheduler.notify_failed", error=str(exc))

    async def _safe_buy_now_scan(self) -> None:
        if self._buy_now is None:
            return
        try:
            await self._buy_now.execute()
        except Exception as exc:
            log.exception("scheduler.buy_now_failed", error=str(exc))

    async def _safe_kleinanzeigen_scan(self) -> None:
        if self._kleinanzeigen is None:
            return
        try:
            await self._kleinanzeigen.execute()
        except Exception as exc:
            log.exception("scheduler.kleinanzeigen_failed", error=str(exc))


def _now_plus_seconds(s: int):  # type: ignore[no-untyped-def]
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) + timedelta(seconds=s)


def _safe(name: str, job: Any) -> Any:
    async def run() -> None:
        try:
            await job()
        except Exception as exc:  # a failed run never stops the loop
            log.exception("job.failed", job=name, error=str(exc)[:200])

    return run
