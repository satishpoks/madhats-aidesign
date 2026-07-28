"""Deterministic profanity scanner — two severity tiers, no model call.

Deliberately PURE: no LLM, no network, no DB. `moderation.check_text` is the
LLM judge and fails open on any error; this one cannot fail at all, which is
what lets the cap-text gate block a design without risking a stall.

Matching is WORD-BOUNDARY ONLY. Substring matching would flag "Scunthorpe",
"assessment" and "classic" — the same class of bug as `state_machine.is_negative`
matching "no" inside "another", which is a documented live landmine here. Leet
variants are listed EXPLICITLY rather than produced by a normalisation pass,
because normalising would reintroduce exactly the false positives the word
boundaries are there to prevent.

Both lists are deliberately conservative: a false positive on the cap path stops
a customer at the very end of the funnel.
"""
from __future__ import annotations

import re

CLEAN = "clean"
MILD = "mild"
SEVERE = "severe"

#: Common obscenity. Tolerated in conversation, blocked on the product.
#:
#: Deliberately EXCLUDES the mildest swears — "hell", "damn", "crap", "bugger".
#: They are printable: blocking a cap reading "HELL RAISERS" is a worse outcome
#: for the store than letting it through, and the cap path is a hard stop at the
#: very end of the funnel. Tune this set, not the matching logic.
MILD_TERMS: frozenset[str] = frozenset({
    "arse", "arsehole", "ass", "asshole", "bastard", "bitch", "bollocks",
    "dick", "dickhead", "dumbass", "fuck", "fucked", "fucker", "fucking",
    "piss", "pissed", "prick", "shit", "shite", "shitty", "slut", "twat",
    "wanker", "whore",
    # Explicit obfuscations — listed, never derived. A general leet-normalising
    # pass would reintroduce exactly the false positives the word boundaries
    # exist to prevent.
    "f*ck", "f**k", "fck", "fuk", "sh*t", "sh1t", "b*tch", "a**hole",
})

#: Slurs and hate terms — declined on sight in chat, and blocked on the product.
#:
#: Sourced from the hate-speech subset of the widely-mirrored LDNOOBW list plus
#: well-documented English-language epithets, covering racial, ethnic,
#: religious, sexual-orientation and gender-identity categories. Terms that are
#: also ordinary words, common surnames, place names or well-known brand names
#: were deliberately left out even when a recognised blocklist carries them —
#: see the exclusion notes in the task report, not reproduced here since this
#: module must stay free of any commentary that could be mistaken for the slurs
#: themselves being ambiguous.
#:
#: Same word-boundary rules apply — check for reclaimed/homographic terms that
#: appear inside ordinary words before adding them.
SEVERE_TERMS: frozenset[str] = frozenset({
    # Anti-Black
    "nigger", "nigga", "niggers", "niggas", "n1gger",
    "jigaboo", "jungle bunny", "porch monkey",
    # Anti-Asian
    "gook", "slanteye", "dothead",
    # Anti-Hispanic/Latino
    "spic", "wetback", "beaner",
    # Anti-Middle Eastern / anti-Arab
    "raghead", "towelhead", "camel jockey",
    # Anti-South Asian
    "paki", "curry muncher",
    # Anti-Native American
    "injun",
    # Antisemitic
    "kike", "heeb",
    # Compound / multi-ethnic
    "sandnigger", "golliwog",
    # Sexual-orientation
    "faggot", "faggots",
    # Gender-identity
    "tranny", "trannies", "shemale", "shemales",
})


def _pattern(terms: frozenset[str]) -> re.Pattern | None:
    """One alternation, longest-first so "fucking" wins over "fuck".

    `(?<!\\w)` / `(?!\\w)` rather than `\\b`: several terms end in a non-word
    character (`f**k`), and `\\b` after `*` asserts the opposite of what is
    meant. Lookarounds around the whole alternation are correct for both.
    """
    if not terms:
        return None
    ordered = sorted(terms, key=len, reverse=True)
    return re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(t) for t in ordered) + r")(?!\w)",
        re.IGNORECASE,
    )


_MILD_RE = _pattern(MILD_TERMS)
_SEVERE_RE = _pattern(SEVERE_TERMS)


def _rebuild() -> None:
    """Recompile from the CURRENT term sets.

    A test seam: it lets `test_profanity` inject a harmless sentinel into
    `SEVERE_TERMS` and exercise the severe tier without the repository or the
    test suite containing actual slurs.
    """
    global _MILD_RE, _SEVERE_RE
    _MILD_RE = _pattern(MILD_TERMS)
    _SEVERE_RE = _pattern(SEVERE_TERMS)


def _matches(pattern: re.Pattern | None, text: str) -> list[str]:
    if pattern is None:
        return []
    return [m.group(0).lower() for m in pattern.finditer(text)]


def scan(text: str | None) -> str:
    """``"clean"`` | ``"mild"`` | ``"severe"`` — severe wins over mild."""
    if not text or not text.strip():
        return CLEAN
    if _matches(_SEVERE_RE, text):
        return SEVERE
    if _matches(_MILD_RE, text):
        return MILD
    return CLEAN


def find_terms(text: str | None) -> list[str]:
    """Matched terms, lowercased and de-duplicated, in first-appearance order.

    Safe to log: terms only, never the surrounding message (security rule 10).
    """
    if not text or not text.strip():
        return []
    seen: dict[str, None] = {}
    for term in _matches(_SEVERE_RE, text) + _matches(_MILD_RE, text):
        seen.setdefault(term, None)
    return list(seen)
