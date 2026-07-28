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
#: NOTE: bare "dick" is deliberately excluded — it collides with the given
#: name/nickname for "Richard" and with the AU retail brand "Dick Smith", and
#: this is a personalised-cap business where a customer's own name is
#: expected input ("Cap for Dick" must stay clean). "dickhead" is unambiguous
#: and is kept.
#: NOTE: "bitch" is kept despite colliding with the kennel-club term for a
#: female dog ("Best in Show Bitch 2026") — the profane reading dominates
#: commercially; this is a deliberate trade-off, not an oversight.
MILD_TERMS: frozenset[str] = frozenset({
    "arse", "arsehole", "ass", "asshole", "bastard", "bitch", "bollocks",
    "dickhead", "dumbass", "fuck", "fucked", "fucker", "fucking",
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
#: NOTE: "spic" is deliberately excluded — it collides with the idiom/cleaning
#: brand "spic and span" (the same reasoning that already excluded the "spick"
#: spelling; keeping one spelling and not the other was inconsistent).
#: "tranny"/"trannies" are deliberately excluded — in Australian/British
#: usage they are common automotive slang for "transmission" ("V8 tranny
#: swap weekend", "manual tranny ute club"), and MadHats is an AU shop where
#: car-club/ute merch is a plausible order category. This is a KNOWN, DELIBERATE
#: coverage gap in the gender-identity slur category, not an oversight — do not
#: re-add without a same-tier-safe way to disambiguate context. "faggot"/
#: "faggots" are kept despite colliding with the traditional British/Irish
#: meatball dish ("faggots and peas") — that dish is rare in Australia and the
#: slur reading dominates overwhelmingly for cap text; this is a deliberate
#: trade-off, not an oversight.
SEVERE_TERMS: frozenset[str] = frozenset({
    # Anti-Black
    "nigger", "nigga", "niggers", "niggas", "n1gger",
    "jigaboo", "jungle bunny", "porch monkey",
    # Anti-Asian
    "gook", "slanteye", "dothead",
    # Anti-Hispanic/Latino
    "wetback", "beaner",
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
    "shemale", "shemales",
})


def _pattern(terms: frozenset[str]) -> re.Pattern | None:
    """One alternation over all terms, matched with word-boundary lookarounds.

    Sorting longest-first is NOT load-bearing for overlapping terms like
    "fuck"/"fucking": the trailing `(?!\\w)` lookahead already rejects a
    "fuck" match sitting inside "fucking" (the next character is a word
    character), so the engine backtracks to the "fucking" alternative
    regardless of alternation order. The sort is harmless and kept for
    readability/determinism (e.g. stable regex source across `_rebuild()`
    calls), not correctness.

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
    """Matched terms, lowercased and de-duplicated.

    Ordering is TIER-first, not text-position-first: every severe match (each
    in first-appearance order) is returned before any mild match (each in its
    own first-appearance order) — mirroring `scan()`'s severe-outranks-mild
    rule. E.g. `"this is shit you <severe-term>"` returns
    `["<severe-term>", "shit"]`, not `["shit", "<severe-term>"]`.

    Safe to log: terms only, never the surrounding message (security rule 10).
    """
    if not text or not text.strip():
        return []
    seen: dict[str, None] = {}
    for term in _matches(_SEVERE_RE, text) + _matches(_MILD_RE, text):
        seen.setdefault(term, None)
    return list(seen)
