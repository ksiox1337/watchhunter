"""Gemini API pricing table. Values verified from ai.google.dev/gemini-api/docs/pricing.

All numbers are USD per 1 token (i.e. the rate from the docs / 1,000,000).
Update when Google publishes new prices.

Note on context tier: 2.5 Pro has a higher rate above 200K input tokens.
Our workload is far below that, so we use the standard rate uniformly.
"""

from __future__ import annotations

from decimal import Decimal

# USD per 1 token (price per 1M tokens / 1_000_000), expressed as Decimal for
# loss-free aggregation when totals get small.
def _per_token(per_million: str) -> Decimal:
    return Decimal(per_million) / Decimal("1000000")


GEMINI_PRICING: dict[str, dict[str, Decimal]] = {
    # Live models (as of 2026-06)
    "gemini-2.5-pro": {
        "input": _per_token("1.25"),
        "output": _per_token("10.00"),
    },
    "gemini-2.5-flash": {
        "input": _per_token("0.30"),
        "output": _per_token("2.50"),
    },
    "gemini-2.5-flash-lite": {
        "input": _per_token("0.10"),
        "output": _per_token("0.40"),
    },
    # Deprecated (shut down 2026-06-01) but kept for historical aggregation
    "gemini-2.0-flash": {
        "input": _per_token("0.10"),
        "output": _per_token("0.40"),
    },
    "gemini-2.0-flash-lite": {
        "input": _per_token("0.075"),
        "output": _per_token("0.30"),
    },
    # DeepSeek V4 (as of 2026-06). Multimodal vision support, JSON structured
    # output, OpenAI-compatible API, no daily request cap.
    "deepseek-chat": {  # V4 Pro tier
        "input": _per_token("0.435"),
        "output": _per_token("0.87"),
    },
    "deepseek-chat-flash": {  # V4 Flash tier — cheapest multimodal
        "input": _per_token("0.14"),
        "output": _per_token("0.28"),
    },
    "deepseek-reasoner": {
        "input": _per_token("0.55"),
        "output": _per_token("2.19"),
    },
}


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Return the USD cost for a single call with the given token counts."""
    p = GEMINI_PRICING.get(model)
    if p is None:
        # Unknown model → no estimate; treat as zero to avoid spurious blocks.
        return Decimal("0")
    return (Decimal(input_tokens) * p["input"]) + (Decimal(output_tokens) * p["output"])
