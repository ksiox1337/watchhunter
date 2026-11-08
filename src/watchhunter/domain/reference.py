"""Normalised watch reference, so sales of the same model can be grouped."""

from __future__ import annotations

import re

_DECADE = re.compile(r"^(19|20)\d\dS?$")  # "1970s" is an era, not a reference
_REF = re.compile(r"\b([A-Z]{1,4})-?(\d{1,4}[A-Z]{0,3})\b|\b()(\d{3,4}[A-Z]?)\b")


def reference_key(brand: str, model: str) -> str:
    """'Seiko', 'A159-4019 G (A159)' -> 'seiko|A159'; '' when no reference number.

    The family part before the dash is the key: case/dial variants of one
    calibre (6309-7290, 6309-7040) are one market for rarity and value.
    """
    b = (brand or "").strip().split(" ")[0].lower()
    m = next(
        (x for x in _REF.finditer((model or "").upper()) if not _DECADE.match(x.group(0))),
        None,
    )
    if not b or not m:
        return ""
    prefix, number = (m.group(1), m.group(2)) if m.group(2) else ("", m.group(4))
    return f"{b}|{prefix}{number}"
