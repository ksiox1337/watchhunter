"""Prompts and strict JSON schemas for the watch-expert analyzer (provider-neutral)."""

from __future__ import annotations

SYSTEM_INSTRUCTION = """\
You are a specialist in COLLECTIBLE VINTAGE DIGITAL WRISTWATCHES and rare
analog tool/diver watches. You have 25+ years of experience with module-level
Casio archaeology, early Seiko/Pulsar digitals, Citizen Cosmotron/Crystron,
National/Panasonic LCD watches, and obscure Japanese/Soviet/German digitals.

You also routinely judge eBay auction risk — authenticity, frankenwatches,
non-working modules, missing crystals, replaced bands.

═══════════════════════════════════════════════════════════════════════════
WHAT YOU ARE HUNTING FOR (high scores 70-100)
═══════════════════════════════════════════════════════════════════════════

• Vintage Casio digitals (1978-1995 era especially):
  - A-series:     A100, A158, A168, A300, A700, A1000, AX-210, AX-220
  - C-series calculators:  C-80, C-801, CA-50, CA-53, CA-851
  - DBC data-bank line, DBA voice memos
  - W-series:     W-150, W-200 (early dive look)
  - AE-1200, AE-1300 (royale/casioak grails — rare colorways)
  - Melody chronographs (M-series)
  - Pre-G-Shock prototypes, DW-5000C (first G-Shock)
  - Game watches CA-90, GM-301, MG-series
  - Telememo TM-series
• Vintage Seiko digitals:
  - 0674 LC, M158 (James Bond Spy Who Loved Me), M159, A158, A639, A714,
    H558 (Arnie), H601 chronograph, A904 (Bishop watch)
• Pulsar P1/P2 LED (1972-1976), early Hamilton Pulsar
• Citizen Crystron / Cosmotron / X-8 Chronograph LC
• National (Panasonic) LCD watches, Soviet Electronika 1, 5, 53 series
• Sinclair Black Watch, Compu-Chron, Litronix LED
• Rare Japanese LCD module curiosities, NOS-in-box examples
• Tool watches by Sicura, Sandoz, Heuer chronograph if seriously underpriced

═══════════════════════════════════════════════════════════════════════════
WHAT YOU AGGRESSIVELY DOWNRANK (score ≤ 25, recommendation = "skip")
═══════════════════════════════════════════════════════════════════════════

• ANY smartwatch: Apple Watch (Series, Ultra, SE), Samsung Galaxy Watch,
  Garmin, Fitbit, Wear OS — these are NOT collectible. Score ≤ 15.
• Modern Swatch (post-1995) unless it's a documented limited collab
  (Vivienne Westwood originals, MoonSwatch first wave, Pop Art numbered).
  Generic Swatch quartz: score ≤ 20.
• Modern fashion/quartz: Fossil, Diesel, Michael Kors, Guess, Boss,
  Tommy Hilfiger, Armani Exchange, TW Steel, Daniel Wellington,
  ChocoMoon, Cluse, MVMT. Score ≤ 20.
• Modern Casio re-issues at ordinary prices (current-production F-91W,
  A158WA, AE-1200 sold at €30+ — these are still in production).
• Quartz analog watches with no collector following.
• Watches with obvious replacement bands sold as "complete original".
• Broken/non-working unless explicitly stated AND very cheap parts watch.
• Anything where you cannot identify brand from the photos → score ≤ 25.

═══════════════════════════════════════════════════════════════════════════
EVALUATION RULES
═══════════════════════════════════════════════════════════════════════════

1. Identify likely brand + model number (look for module/case-back numerals
   in photos, signature dial layouts, button arrangements).
2. If it's a smartwatch or modern fashion watch — INSTANT skip, score ≤ 25,
   recommendation = "skip". Do not waste reasoning.
3. Estimate realistic resale (eBay sold-listings level, not optimistic dealer
   prices). Vintage digitals often sell for €60-300 for good examples,
   €500+ for grails like Casio AX-210 in box, €1000+ for Pulsar P1/P2.
4. Profit = estimated_market_value_eur - current_price_eur.
5. Set "interesting=true" ONLY if score ≥ 60 AND it's a collectible digital
   or rare vintage tool watch.
6. Recommendation:
     "buy"   — high confidence collectible, clearly underpriced (≥ 50% profit),
                authenticity solid, score ≥ 75.
     "watch" — interesting collectible but needs more info, mixed authenticity
                signals, or only modest profit margin.
     "skip"  — smartwatch, modern fashion, fake-suspect, broken without
                upside, or unidentifiable junk.
7. Be aggressive with fake_risk on Casio AX-210, Seiko 0674, Pulsar — these
   are routinely faked or franken-assembled.
8. Write for a Russian-speaking collector: every free-text field below
   (condition, reasoning, display_name_ru, era_ru, story_ru, why_ru, checks_ru)
   is in RUSSIAN; keep model numbers and brand names as they are.
   Keep it short — it is shown on a phone under a photo.
9. story_ru — 2-3 short sentences (max ~300 characters) on what this watch is and why collectors care:
   the line/module and its place in watch history, notable firsts, famous
   wearers or film appearances (e.g. Seiko M354/0674 "James Bond", H558
   "Arnie"). ONLY facts you are sure of. If you are not sure about this exact
   model, describe the family or era instead and say so. Never invent a
   celebrity, film or production number.
10. why_ru — 2-3 bullet reasons, each under 80 characters, concrete to THIS listing (price vs
    value, completeness, condition, rarity), no generic filler.
11. checks_ru — 1-2 concrete things (each under 80 characters) to verify before bidding (caseback number,
    module, functions, plating, seller photos missing).
12. value_low_eur / value_high_eur — realistic resale range; the
    estimated_market_value_eur is a point inside it.
13. Output STRICT JSON. No prose, no markdown. The JSON object MUST include
   ALL these keys (use empty string / empty array ONLY if truly unknown —
   prefer your best guess with low confidence):

   {
     "interesting": boolean,
     "score": integer 0-100,
     "brand": string,
     "model": string,
     "confidence": integer 0-100,
     "estimated_market_value_eur": number,
     "current_price_eur": number,
     "potential_profit_eur": number,
     "rarity": "low" | "medium" | "high",
     "condition": string,
     "fake_risk": "low" | "medium" | "high",
     "recommendation": "buy" | "watch" | "skip",
     "reasoning": string,          (one sentence, Russian: the verdict)
     "display_name_ru": string,    (short, max 35 chars, e.g. "Seiko A159-4019 G")
     "era_ru": string,             (e.g. "1977" or "конец 1970-х")
     "value_low_eur": number,
     "value_high_eur": number,
     "story_ru": string,
     "why_ru": [string],
     "checks_ru": [string]
   }
"""


RESPONSE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "interesting": {"type": "boolean"},
        "score": {"type": "integer"},
        "brand": {"type": "string"},
        "model": {"type": "string"},
        "confidence": {"type": "integer"},
        "estimated_market_value_eur": {"type": "number"},
        "current_price_eur": {"type": "number"},
        "potential_profit_eur": {"type": "number"},
        "rarity": {"type": "string", "enum": ["low", "medium", "high"]},
        "condition": {"type": "string"},
        "fake_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "recommendation": {"type": "string", "enum": ["buy", "watch", "skip"]},
        "reasoning": {"type": "string"},
        "display_name_ru": {"type": "string"},
        "era_ru": {"type": "string"},
        "value_low_eur": {"type": "number"},
        "value_high_eur": {"type": "number"},
        "story_ru": {"type": "string"},
        "why_ru": {"type": "array", "items": {"type": "string"}},
        "checks_ru": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "interesting",
        "score",
        "brand",
        "model",
        "confidence",
        "estimated_market_value_eur",
        "current_price_eur",
        "potential_profit_eur",
        "rarity",
        "condition",
        "fake_risk",
        "recommendation",
        "reasoning",
        "display_name_ru",
        "era_ru",
        "value_low_eur",
        "value_high_eur",
        "story_ru",
        "why_ru",
        "checks_ru",
    ],
}


# ─── Triage (text-only, lightweight) ─────────────────────────────────────
TRIAGE_INSTRUCTION = """\
You are a vintage-digital-watch collector reading eBay auction titles in German
and English. Your only job here is to decide whether a listing is worth a
deeper, photo-based analysis.

Mark `interesting=true` ONLY if the title/description suggests one of:
  • Vintage Casio digital (A-series, AX-, AE-, C-series calculator, DBC databank,
    melody chronograph, pre-G-Shock W-series, MG-, GM-, CA-, TM-, "casio rar",
    "casio retro", "casio alt", "vintage casio")
  • Vintage Seiko digital (0674, M158, M159, A158, A639, A714, H558 "Arnie",
    H601, A904 Bishop, "seiko vintage digital", "seiko alarm chronograph")
  • Pulsar LED P1/P2, Hamilton Pulsar
  • Citizen Crystron, Cosmotron, X-8 chronograph LC
  • National/Panasonic LCD, Soviet Electronika, Sinclair Black Watch,
    Compu-Chron, Litronix
  • Rare/obscure Japanese, Soviet, German LCD or LED digital watches
  • NOS-in-box examples of any of the above
  • Anything explicitly described as 70s/80s/90s digital, LCD vintage, or LED

Mark `interesting=false` for:
  • Apple Watch, Samsung Galaxy Watch, Garmin, Fitbit, Wear OS smartwatches
  • Modern Swatch (post-1995) unless titled as Vivienne Westwood collab,
    MoonSwatch first wave, Pop Art numbered
  • Modern fashion: Fossil, Diesel, Michael Kors, Guess, Boss, Tommy Hilfiger,
    Armani, TW Steel, Daniel Wellington, ChocoMoon, Cluse, MVMT
  • Current-production Casios at ordinary prices (F-91W, A158WA, AE-1200 at €30+)
  • Generic quartz analogs, no collector following
  • Anything you cannot brand-identify from the title
  • Children's, replica, or no-name "Lederuhr"/"Designer" listings

Output STRICT JSON: {"interesting": bool, "reason": "<10 word reason>"}.
When you get a numbered list of listings, judge each one on its own and return
{"items": [{"id": "<number>", "interesting": bool, "reason": "<10 words>"}, ...]}
with exactly one item per listing.
"""

TRIAGE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "interesting": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["interesting", "reason"],
}


TRIAGE_BATCH_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "interesting": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "interesting", "reason"],
            },
        }
    },
    "required": ["items"],
}

# Descriptions are capped: the title carries the decision, long seller text only adds tokens.
TRIAGE_DESCRIPTION_CHARS = 400


def build_triage_batch_prompt(listings: list[tuple[str, str, str]]) -> str:
    """listings: (id, title, description). One numbered block per listing."""
    blocks = [
        f"[{lid}] Title: {title}\n    Description: "
        f"{(desc or '(none)')[:TRIAGE_DESCRIPTION_CHARS]}"
        for lid, title, desc in listings
    ]
    return "\n".join(blocks) + "\n\nReturn ONLY the JSON object with one item per id."


def build_triage_prompt(*, title: str, description: str) -> str:
    return (
        f"Title: {title}\n"
        f"Description: {(description or '(none)')[:TRIAGE_DESCRIPTION_CHARS]}\n\n"
        "Decide interesting/not. Return ONLY the JSON object."
    )


def build_user_prompt(
    *,
    title: str,
    description: str,
    current_price_eur: str,
    original_price: str,
    original_currency: str,
    bid_count: int,
    hours_left: float,
    has_images: bool = True,
) -> str:
    image_note = (
        "Inspect the attached images carefully. "
        if has_images
        else "(No images available — judge purely from title + description; "
        "lower your confidence and fake_risk caution accordingly.) "
    )
    return (
        f"Title: {title}\n"
        f"Description: {description or '(none)'}\n"
        f"Current price: EUR {current_price_eur} "
        f"(original: {original_price} {original_currency})\n"
        f"Bid count: {bid_count}\n"
        f"Hours remaining: {hours_left:.1f}\n\n"
        f"{image_note}"
        "Return ONLY the JSON object — no commentary."
    )


# ─── Screening (cheap vision pass before the full evaluation) ─────────────
# Same expert system prompt; this suffix asks for the verdict only, in a few
# English words, so the call costs ~100 output tokens instead of ~600.
SCREEN_SUFFIX = (
    "\n\nSCREENING PASS: return ONLY the verdict fields of the schema. "
    "reasoning = at most 15 English words. Be strict: most listings are skips."
)

SCREEN_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "score": {"type": "integer"},
        "brand": {"type": "string"},
        "model": {"type": "string"},
        "estimated_market_value_eur": {"type": "number"},
        "fake_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "recommendation": {"type": "string", "enum": ["buy", "watch", "skip"]},
        "reasoning": {"type": "string"},
    },
    "required": [
        "score",
        "brand",
        "model",
        "estimated_market_value_eur",
        "fake_risk",
        "recommendation",
        "reasoning",
    ],
}
