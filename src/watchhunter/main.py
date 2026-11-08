"""Application entry point."""

from __future__ import annotations

import asyncio
import fcntl
import os
import signal
import sys
from pathlib import Path
from typing import IO

from watchhunter.config.logging import configure_logging, get_logger
from watchhunter.config.settings import get_settings
from watchhunter.container import build_container

log = get_logger(__name__)


async def _run() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json=settings.log_json)
    log.info(
        "app.starting",
        version="0.1.0",
        ebay_api=settings.ebay_use_api,
        marketplaces=settings.ebay_marketplaces,
        min_score=settings.min_score,
    )

    container = await build_container(settings)
    container.scheduler.start()

    stop = asyncio.Event()

    def _signal() -> None:
        log.info("app.signal_received")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal)
        except NotImplementedError:
            # Windows or non-main thread
            pass

    try:
        await stop.wait()
    finally:
        log.info("app.shutting_down")
        await container.aclose()
        log.info("app.stopped")


def _single_instance(lock_path: Path) -> IO[str]:
    """Exit if another WatchHunter already runs: two copies would double every
    scan, every model call and every Telegram message."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(f"WatchHunter is already running (lock {lock_path}). Stop it first.")
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def main() -> None:
    if sys.argv[1:2] == ["check"]:
        from watchhunter.check import main as check

        sys.exit(check())
    _lock = _single_instance(Path("data") / "watchhunter.lock")  # held until exit
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
