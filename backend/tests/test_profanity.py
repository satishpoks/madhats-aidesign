"""The scanner is pure — no LLM, no I/O — so it can never stall a turn.

Severe-tier tests inject synthetic sentinels via `_rebuild()` rather than
hardcoding slurs, so the suite stays readable and the real list can change
without touching these tests.
"""
import pytest

from app.services import profanity


@pytest.fixture
def severe_sentinel(monkeypatch):
    """Swap the severe list for a harmless sentinel and recompile."""
    monkeypatch.setattr(profanity, "SEVERE_TERMS", frozenset({"zzslur"}))
    profanity._rebuild()
    yield "zzslur"
    monkeypatch.undo()
    profanity._rebuild()


@pytest.mark.parametrize("text", [
    "",
    None,
    "I need 50 caps for our club",
    # Substring traps. Matching inside words is the Scunthorpe problem and the
    # exact shape of the documented is_negative("another" contains "no") bug.
    "Scunthorpe United",
    "please send an assessment",
    "a classic six-panel",
    "Cockburn Rangers",
    "Essex County",
    "shitake mushrooms are not a swear word",
    "Bassetlaw",
])
def test_clean_text_is_clean(text):
    assert profanity.scan(text) == "clean"


@pytest.mark.parametrize("text", [
    "this is fucking slow",
    "that looks like shit",
    "F*CK this thing",
    "you absolute wanker",
])
def test_mild_profanity_is_mild(text):
    assert profanity.scan(text) == "mild"


def test_severe_terms_are_severe(severe_sentinel):
    assert profanity.scan(f"you {severe_sentinel}") == "severe"


def test_severe_outranks_mild_in_the_same_message(severe_sentinel):
    assert profanity.scan(f"this is shit you {severe_sentinel}") == "severe"


def test_find_terms_returns_matches_deduplicated_in_order():
    assert profanity.find_terms("shit, piss, shit again") == ["shit", "piss"]


def test_find_terms_is_empty_for_clean_text():
    assert profanity.find_terms("a navy trucker cap") == []


def test_matching_is_case_insensitive():
    assert profanity.scan("SHIT") == "mild"


def test_the_two_tiers_do_not_overlap():
    assert not (profanity.MILD_TERMS & profanity.SEVERE_TERMS)


def test_the_severe_list_is_populated():
    """An empty severe list makes the chat decline in orchestrator_v2 dead code."""
    assert profanity.SEVERE_TERMS


def test_scan_never_raises_on_odd_input():
    for value in (None, "", "   ", "🎩", "a" * 10_000):
        assert profanity.scan(value) in {"clean", "mild", "severe"}
