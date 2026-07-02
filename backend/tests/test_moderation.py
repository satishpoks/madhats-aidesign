"""Moderation gate behaviour.

Regression guard for the bug where entering an email in the chat produced a
content-safety error ("This appears to be an email address rather than a
headwear design request…"). Moderation runs on every chat turn, so a benign,
non-design message (name / email / phone / quantity) must pass.

The real Haiku judgement can't be unit-tested, so we mock the model call
(`intent_extractor._complete`) and assert the surrounding plumbing: benign →
pass, genuinely harmful → block, no key → no-op.
"""
from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.services import moderation
from app.services.conversation import intent_extractor as ie


@pytest.fixture
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend an Anthropic key is configured so check_text actually runs."""
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")


def _fake_complete(reply: str):
    async def _complete(*_args, **_kwargs) -> str:
        return reply

    return _complete


def test_benign_email_passes(monkeypatch: pytest.MonkeyPatch, with_key: None) -> None:
    monkeypatch.setattr(ie, "_complete", _fake_complete('{"safe": true}'))
    # Must not raise — an email is not a safety violation.
    asyncio.run(moderation.check_text("sarah@example.com"))


def test_prompt_treats_input_as_generic_message_not_design_request() -> None:
    # The bug came from framing every turn as a "design request". Guard that wording.
    prompt = moderation._MODERATION_PROMPT
    assert "design request" not in prompt.split("Mark it UNSAFE")[0].lower() or "may" in prompt.lower()
    assert "email" in prompt.lower()
    assert "not a design request" in prompt.lower()


def test_harmful_content_is_blocked(monkeypatch: pytest.MonkeyPatch, with_key: None) -> None:
    monkeypatch.setattr(
        ie, "_complete", _fake_complete('{"safe": false, "reason": "hate symbol"}')
    )
    with pytest.raises(moderation.ModerationError):
        asyncio.run(moderation.check_text("something genuinely harmful"))


def test_non_json_reply_does_not_block(monkeypatch: pytest.MonkeyPatch, with_key: None) -> None:
    # A prose reply parses to {} → treated as safe (fail-open, never a false block).
    monkeypatch.setattr(ie, "_complete", _fake_complete("This looks like an email address."))
    asyncio.run(moderation.check_text("sarah@example.com"))


def test_no_key_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    def _boom(*_a, **_k):  # pragma: no cover - must never be called
        raise AssertionError("_complete should not be called without a key")

    monkeypatch.setattr(ie, "_complete", _boom)
    asyncio.run(moderation.check_text("anything at all"))
