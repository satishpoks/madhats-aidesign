"""Email format validation on the v2 canvas capture path.

Before this, the healthy path had none: `interpret_turn_v2` filled the `email`
slot, `validate_fields` passed it through untouched (no enum, no coercion), and
`_apply_email` handed the raw string to `capture_lead_and_verify`, which INSERTs
it. `leads._EMAIL_RE` existed but is an UNANCHORED extractor used only by v1 and
the Haiku-outage fallback. In dev/CI (`delivery_ok = sent or not
provider_configured`) a garbage address was even marked captured, marching the
customer to the verification gate behind a link that could never arrive.
"""
from __future__ import annotations

import pytest

from app import prompts
from app.services import leads as leads_service
from app.services.conversation import canvas_steps as cs
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation.state_machine import ConversationState as S


VALID = [
    "a@b.co",                      # the shortest thing we accept
    "sam@example.com",
    "SAM@EXAMPLE.COM",
    "first.last@example.co.uk",
    "sam+studio@example.com",
    "sam_1-2@sub.example.com",
    "a" * 64 + "@example.com",     # local part exactly at the RFC limit
]

INVALID = [
    None,
    "",
    "   ",
    "nope",                        # no @ at all
    "john at gmail",               # words, not an address
    "a@b",                         # domain with no dot
    "a@@b.co",                     # more than one @
    "a@b@c.co",
    "a b@c.co",                    # whitespace in the local part
    "a@b c.co",                    # whitespace in the domain
    " a@b.co",                     # untrimmed — the caller strips, not us
    "a@b.co ",
    ".a@b.co",                     # leading dot in the local part
    "a.@b.co",                     # trailing dot in the local part
    "a@.b.co",                     # leading dot in the domain
    "a@b.co.",                     # trailing dot in the domain
    "a@b..co",                     # consecutive dots
    "a..b@c.co",
    "a@b.c",                       # single-character TLD
    "@b.co",                       # empty local part
    "a@",                          # empty domain part
    "a" * 65 + "@example.com",     # local part one over the RFC limit
    "a" * 250 + "@example.com",    # over the 254-character total limit
]


@pytest.mark.parametrize("address", VALID)
def test_is_valid_email_accepts(address):
    assert leads_service.is_valid_email(address) is True


@pytest.mark.parametrize("address", INVALID)
def test_is_valid_email_rejects(address):
    assert leads_service.is_valid_email(address) is False


def test_extract_email_is_left_alone():
    """`extract_email` is a deliberately LOOSE extractor (unanchored search)
    used by v1 and the outage fallback to answer "did they give us an address
    yet?". Tightening it would change v1 behaviour; validation is a separate,
    additive function."""
    assert leads_service.extract_email("my email is sam@example.com, thanks") == \
        "sam@example.com"


# --- the capture site ---------------------------------------------------------

def test_apply_email_sets_nothing_for_an_invalid_address(monkeypatch):
    """No lead_id, no email_captured — exactly the existing failure path, so
    ASK_EMAIL.done_when stays unmet and the step re-asks itself."""
    def _boom(*_a, **_k):
        raise AssertionError("a malformed address must never reach the leads table")
    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify", _boom)

    step = cs.by_id(S.ASK_EMAIL)
    # ASK_EMAIL is deliberately SATISFIED until the first element is placed, so
    # a bare {} would pass done_when for a reason that has nothing to do with
    # this fix. Place a logo first, which is what makes the step current.
    c: dict = {"logos": [{"face": "front", "placed": True}]}
    step.apply(c, {"email": "john at gmail"}, {"id": "s1"})

    assert "lead_id" not in c
    assert not c.get("email_captured")
    assert "email" not in c              # and the raw string is not left behind
    assert not step.done_when(c)         # -> ask_email re-asks


@pytest.mark.parametrize("raw", [None, 123, {"address": "sam@example.com"}, ["a@b.co"]])
def test_apply_email_survives_a_non_string_slot(raw, monkeypatch):
    """`validate_fields` gives the `email` slot no coercion, so a model that
    returns the wrong shape reaches this apply as-is. It must be rejected, not
    500 the turn on `.strip()`."""
    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify",
                        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no")))

    c: dict = {}
    cs.by_id(S.ASK_EMAIL).apply(c, {"email": raw}, {"id": "s1"})
    assert not c.get("email_captured")


def test_apply_email_still_captures_a_valid_address(monkeypatch):
    seen: dict = {}

    def _fake(session, collected, email):
        seen.update(session=session, email=email)
        return "lead-1", True

    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify", _fake)

    c: dict = {}
    cs.by_id(S.ASK_EMAIL).apply(c, {"email": "sam@example.com"}, {"id": "s1"})

    assert c["email_captured"] is True and c["lead_id"] == "lead-1"
    assert seen["email"] == "sam@example.com"


def test_apply_email_trims_before_validating_and_capturing(monkeypatch):
    """A trailing space is a typo, not a rejection: the caller strips, so
    `is_valid_email` itself can stay strict."""
    seen: dict = {}
    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify",
                        lambda s, c, e: (seen.update(email=e) or ("lead-1", True)))

    c: dict = {}
    cs.by_id(S.ASK_EMAIL).apply(c, {"email": "  sam@example.com  "}, {"id": "s1"})

    assert seen["email"] == "sam@example.com"
    assert c["email_captured"] is True


def test_direct_email_rejects_a_malformed_address():
    """The Haiku-outage fallback must not be a way around the validator.
    `extract_email` is unanchored, so it happily pulls "a@b.c" out of prose."""
    assert cs._direct_email("my address is a@b.c") == {}
    assert cs._direct_email("no address here") == {}
    assert cs._direct_email("it's sam@example.com") == {"email": "sam@example.com"}


# --- retry copy ---------------------------------------------------------------

def test_ask_email_declares_retry_copy():
    assert cs.by_id(S.ASK_EMAIL).ask_retry == prompts.V2_ASK_EMAIL_RETRY


def test_the_second_ask_uses_the_retry_copy():
    """`reply_for` swaps in `ask_retry` once the step is in `_asked` — which the
    orchestrator appends on the turn the customer answered. Without this, a
    rejected address re-renders the identical full-length question with no
    acknowledgement that anything was wrong."""
    step = cs.by_id(S.ASK_EMAIL)
    first = v2.reply_for(step, {"name": "Sam"}, persona="Ricardo", intro="")
    retry = v2.reply_for(step, {"name": "Sam", "_asked": [S.ASK_EMAIL.value]},
                         persona="Ricardo", intro="")

    assert first != retry
    assert retry == prompts.V2_ASK_EMAIL_RETRY
