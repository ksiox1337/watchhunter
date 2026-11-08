"""structlog configuration. Initialise once at startup via `configure_logging()`."""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

import structlog


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)
    # Remove any preexisting handlers (e.g. when re-configuring in tests).
    for h in list(root.handlers):
        root.removeHandler(h)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(stdout_handler)

    # Daily-rotated file log for offline analysis. Keeps 14 days.
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        logs_dir / "watchhunter.log",
        when="midnight",
        backupCount=14,
        encoding="utf-8",
        utc=True,
    )
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(file_handler)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
