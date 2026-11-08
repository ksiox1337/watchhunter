"""Tiny static FX table for MVP. Swap for a live FX adapter when needed."""

from __future__ import annotations

from decimal import Decimal

# Approximate static rates → EUR. Good enough for MVP filtering;
# the Gemini analysis is the source of truth on market value.
_TO_EUR: dict[str, Decimal] = {
    "EUR": Decimal("1.0"),
    "USD": Decimal("0.92"),
    "GBP": Decimal("1.17"),
    "CHF": Decimal("1.05"),
    "JPY": Decimal("0.0061"),
    "CAD": Decimal("0.68"),
    "AUD": Decimal("0.61"),
}


def to_eur(amount: Decimal, currency: str) -> Decimal:
    rate = _TO_EUR.get(currency.upper())
    if rate is None:
        # Unknown currency → treat 1:1 to avoid raising in the hot path.
        # Logged upstream; analyzer corrects this anyway.
        return amount
    return (amount * rate).quantize(Decimal("0.01"))
