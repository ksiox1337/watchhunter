"""Domain-level exception hierarchy."""

from __future__ import annotations


class DomainError(Exception):
    """Root of all WatchHunter exceptions."""


class MarketplaceError(DomainError):
    """Raised by marketplace adapters when listings cannot be fetched."""


class AnalyzerError(DomainError):
    """Raised by analyzer adapters when evaluation fails."""


class NotifierError(DomainError):
    """Raised by notification adapters when delivery fails."""


class ConfigurationError(DomainError):
    """Raised when configuration is missing or invalid."""


class BudgetExhaustedError(DomainError):
    """Raised when the daily Gemini spend cap would be exceeded by a call."""
