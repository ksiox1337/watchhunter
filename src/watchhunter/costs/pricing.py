"""LLM pricing table (USD per token). Source: openai.com/api/pricing, checked 2026-11.

`cached_input` is what OpenAI bills for prompt tokens served from its automatic
prompt cache (a repeated prefix of >= 1024 tokens). Older rows stay so that
historical usage rows in the database still price correctly.
"""

from __future__ import annotations

from decimal import Decimal


def _per_token(per_million: str) -> Decimal:
    return Decimal(per_million) / Decimal("1000000")


def _row(inp: str, out: str, cached: str | None = None) -> dict[str, Decimal]:
    return {
        "input": _per_token(inp),
        "output": _per_token(out),
        "cached_input": _per_token(cached if cached is not None else inp),
    }


PRICING: dict[str, dict[str, Decimal]] = {
    # OpenAI (current)
    "gpt-5-nano": _row("0.05", "0.40", "0.005"),
    "gpt-5-mini": _row("0.25", "2.00", "0.025"),
    "gpt-5": _row("1.25", "10.00", "0.125"),
    "gpt-4.1-nano": _row("0.10", "0.40", "0.025"),
    "gpt-4.1-mini": _row("0.40", "1.60", "0.10"),
    "gpt-4o-mini": _row("0.15", "0.60", "0.075"),
    # TypeSafe Jev (aggregator figures, early access; check typesafe.ai)
    "jev": _row("0.04", "0"),
    # Historical (previous Gemini / DeepSeek setup)
    "gemini-2.5-pro": _row("1.25", "10.00"),
    "gemini-2.5-flash": _row("0.30", "2.50"),
    "gemini-2.5-flash-lite": _row("0.10", "0.40"),
    "gemini-2.0-flash": _row("0.10", "0.40"),
    "gemini-2.0-flash-lite": _row("0.075", "0.30"),
    "deepseek-chat": _row("0.435", "0.87"),
    "deepseek-reasoner": _row("0.55", "2.19"),
}


def _lookup(model: str) -> dict[str, Decimal] | None:
    if model in PRICING:
        return PRICING[model]
    # Dated snapshots, e.g. "gpt-5-mini-2025-08-07" -> "gpt-5-mini".
    for name in sorted(PRICING, key=len, reverse=True):
        if model.startswith(name + "-"):
            return PRICING[name]
    return None


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> Decimal:
    """USD cost of one call. `input_tokens` includes the cached ones (OpenAI usage format)."""
    p = _lookup(model)
    if p is None:
        return Decimal("0")
    cached = min(cached_input_tokens, input_tokens)
    return (
        Decimal(input_tokens - cached) * p["input"]
        + Decimal(cached) * p["cached_input"]
        + Decimal(output_tokens) * p["output"]
    )
