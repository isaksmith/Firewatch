"""Sort a free-text message into a board category. Pure, no I/O."""
from __future__ import annotations

import re
from typing import NamedTuple

WORDS = {
    "fire": ("fire", "flames", "flame", "blaze", "burning", "wildfire", "grassfire"),
    "smoke": ("smoke", "smoking", "smoky"),
    "hazard": ("downed", "line", "lines", "pole", "sparking", "sparks", "arcing", "wire", "wires", "transformer"),
    "burn": ("burn", "burning pile", "controlled", "prescribed"),
}
HEARSAY = ("heard", "someone said", "they say")
NEGATION = ("no fire", "no smoke", "put out", "not a fire", "not fire")
ORDER = ("fire", "smoke", "hazard", "burn")


class Sorted(NamedTuple):
    category: str
    hearsay: bool
    matched: tuple


def _has(text: str, phrase: str) -> bool:
    return re.search(r"\b" + r"\s+".join(map(re.escape, phrase.split())) + r"\b", text) is not None


def classify(text: str) -> Sorted:
    t = (text or "").lower()
    hearsay = any(_has(t, h) for h in HEARSAY)
    if any(_has(t, n) for n in NEGATION):
        return Sorted("other", hearsay, ())
    for cat in ORDER:
        hit = tuple(w for w in WORDS[cat] if _has(t, w))
        if cat == "fire":
            hit = tuple(w for w in hit if w != "burning" or not _has(t, "burning pile"))
        if hit:
            return Sorted(cat, hearsay, hit)
    return Sorted("other", hearsay, ())
