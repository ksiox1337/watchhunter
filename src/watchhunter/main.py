"""Application entry point."""

from __future__ import annotations

import asyncio
import signal

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


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
