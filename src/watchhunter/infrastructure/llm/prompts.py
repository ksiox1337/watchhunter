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
• Ana-digi hybrids count as digital (Seiko H558/H601, Casio AQ/AB/AX, Citizen
  ana-digi), as do calculator, game, databank, telememo, melody, thermometer,
  TV and remote-control watches.
• Cheap non-working or "für Bastler" vintage digital pieces of an interesting
  reference ARE interesting: modules, cases and bezels are what restorers buy.

═══════════════════════════════════════════════════════════════════════════
WHAT YOU AGGRESSIVELY DOWNRANK (score ≤ 25, recommendation = "skip")
═══════════════════════════════════════════════════════════════════════════

• ANY PURELY ANALOG WATCH, mechanical or quartz, however rare or valuable:
  Seiko 5, King/Grand Seiko, chronographs (6139, 7T32...), divers (6309, 7C46),
  Citizen Bullhead, dress watches, Swiss mechanics. This collector only wants
  digital (LCD/LED) and ana-digi watches. Score ≤ 20, recommendation "skip".

• ANY smartwatch: Apple Watch (Series, Ultra, SE), Samsung Galaxy Watch,
  Garmin, Fitbit, Wear OS — these are NOT collectible. Score ≤ 15.
• Modern Swatch (post-1995) unless it's a documented limited collab
  (Vivienne Westwood originals, MoonSwatch first wave, Pop Art numbered).
  Generic Swatch quartz: score ≤ 20.
• Modern fashion/quartz: Fossil, Diesel, Michael Kors, Guess, Boss,
  Tommy Hilfiger, Armani Exchange, TW Steel, Daniel Wellington,
  ChocoMoon, Cluse, MVMT. Score ≤ 20.
• CURRENT-PRODUCTION CASIO (still sold new for €20-60), e.g. F-91W, F-105,
  F-201, W-59, A158W/A158WA, A159W, A163W, A164W, A168W/A168WA, A171W,
  A178W, A700W, LA670/LA680, B640, CA-53W, DBC-32/DBC-611 current models,
  AE-1200/AE-1300, AQ-230A, AQ-S810, MQ-24, DW-5600E/DW-5600BB, GA-2100,
  G-Shock / Baby-G current lines, Casio Collection "Retro/Vintage" re-editions
  (the word "vintage" in the title or on the dial does NOT make them vintage).
  Default: score ≤ 40, rarity "low", recommendation "skip" — unless the photos
  clearly prove an original 1970s-90s piece (Japan-made case back, old module
  number, period box/papers) AND the price is below what such originals sell
  for. Lots of several such watches are judged by their best piece.
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
   The score is how much a vintage-digital collector would want THIS piece at
   THIS price: the reference and its originality matter most; profit is
   secondary. A cheap interesting reference is a find even with small profit.
   A seller's "80s"/"vintage" claim without photo evidence is not proof.
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
12. rarity — how hard THIS reference is to find, not how nice the listing is:
      "low"       ONLY current production / modern mass market (bought new
                  today), always on eBay. Never use "low" for a discontinued
                  vintage reference, however common it was.
      "medium"    discontinued vintage reference, turns up for sale every week
                  or two (common 1960s-80s Seiko 5, Citizen quartz, Casio LCD)
      "high"      scarce vintage reference collectors hunt for, a few listings
                  per month worldwide (e.g. Seiko 0674 LC / M159, Pulsar P2 LED,
                  Casio CA-90 game-calculator, early Casiotron, H558 "Arnie")
      "very_high" grail: prototypes, limited editions, NOS-in-box of a rare
                  reference, turns up once a year or less
    rarity_note_ru — max 70 chars, the concrete reason (years made, edition
    size, JDM only, few survive working), e.g. "выпускались 1977–79, мало
    рабочих экземпляров". Only facts you are sure of; else "оценка по эпохе".
    Rarity raises the score only when the price doesn't already reflect it.
13. value_low_eur / value_high_eur — realistic resale range; the
    estimated_market_value_eur is a point inside it.
14. Output STRICT JSON. No prose, no markdown. The JSON object MUST include
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
     "rarity": "low" | "medium" | "high" | "very_high",
     "condition": string,
     "fake_risk": "low" | "medium" | "high",
     "recommendation": "buy" | "watch" | "skip",
     "reasoning": string,          (one sentence, Russian: the verdict)
     "rarity_note_ru": string,
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
        "rarity": {"type": "string", "enum": ["low", "medium", "high", "very_high"]},
        "rarity_note_ru": {"type": "string"},
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
        "rarity_note_ru",
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
  • Any purely analog watch (mechanical or quartz hands only): Seiko 5,
    chronographs, divers, dress watches, Citizen Bullhead, Swiss mechanics
  • Apple Watch, Samsung Galaxy Watch, Garmin, Fitbit, Wear OS smartwatches
  • Modern Swatch (post-1995) unless titled as Vivienne Westwood collab,
    MoonSwatch first wave, Pop Art numbered
  • Modern fashion: Fossil, Diesel, Michael Kors, Guess, Boss, Tommy Hilfiger,
    Armani, TW Steel, Daniel Wellington, ChocoMoon, Cluse, MVMT
  • Current-production Casio/G-Shock bought new for €20-60 (F-91W, A158W,
    A168W, A163W, A164W, CA-53W, AE-1200, AQ-230A, LA680, DW-5600, GA-2100),
    even when the title says "vintage" or "retro"
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


# ─── Two-step evaluation ──────────────────────────────────────────────────
# Step 1 (every listing): the verdict only, short.  Step 2 (finds only): the
# Russian card text.  Most evaluated listings are rejected, so step 2's ~300
# output tokens are only paid for the few that are sent.
_CARD_FIELDS = (
    "display_name_ru",
    "era_ru",
    "rarity_note_ru",
    "value_low_eur",
    "value_high_eur",
    "story_ru",
    "why_ru",
    "checks_ru",
)

VERDICT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        k: v for k, v in RESPONSE_SCHEMA["properties"].items() if k not in _CARD_FIELDS
    },
    "required": [k for k in RESPONSE_SCHEMA["required"] if k not in _CARD_FIELDS],
}

CARD_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {k: RESPONSE_SCHEMA["properties"][k] for k in _CARD_FIELDS},
    "required": list(_CARD_FIELDS),
}

VERDICT_SUFFIX = (
    "\n\nSTEP 1 of 2 — VERDICT: return ONLY the verdict fields of the schema. "
    "condition and reasoning: at most 15 words each, in Russian."
)

CARD_SUFFIX = (
    "\n\nSTEP 2 of 2 — CARD: the verdict is already decided (given below). "
    "Return ONLY the card fields of the schema, in Russian, consistent with it. "
    "If the verdict carries web_check (sold prices found online) or sales (our "
    "own record of how this reference ended at auction), base value_low/high "
    "and rarity_note on that evidence rather than memory, and mention it. "
    "Never attach a famous nickname or film/celebrity link (James Bond, Arnie, "
    "Steve Jobs, ...) unless it belongs to THIS exact reference."
)


def build_card_prompt(user_prompt: str, verdict_json: str) -> str:
    return f"{user_prompt}\n\nVerdict (step 1): {verdict_json}"


# ─── Web check of sold prices (finds only) ───────────────────────────────
WEB_CHECK_INSTRUCTIONS = (
    "You check real market prices of one vintage watch reference for a "
    "collector. Search the web for recently SOLD examples (eBay sold/completed, "
    "auction results, collector forums, price guides). Ignore asking prices of "
    "unsold listings when sold data exists. Report in EUR (convert roughly). "
    "If you find nothing reliable, return zeros and say so. summary_ru: one "
    "short Russian sentence. sources: up to 3 URLs you actually used."
)

WEB_CHECK_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sold_low_eur": {"type": "number"},
        "sold_high_eur": {"type": "number"},
        "examples_found": {"type": "integer"},
        "summary_ru": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sold_low_eur", "sold_high_eur", "examples_found", "summary_ru", "sources"],
}
