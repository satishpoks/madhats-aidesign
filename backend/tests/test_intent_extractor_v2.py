import pytest

from app.services.conversation import canvas_steps as cs
from app.services.conversation import intent_extractor as ie
from app.services.conversation.state_machine import ConversationState as S


def test_validate_drops_undeclared_slots():
    got = ie.validate_fields({"name": "Sam", "email_captured": True, "logos": ["x"]})
    assert got == {"name": "Sam"}          # internal keys are not writable


def test_validate_enforces_enums():
    assert ie.validate_fields({"logo_face": "back"}) == {"logo_face": "back"}
    assert ie.validate_fields({"logo_face": "brim"}) == {}
    assert ie.validate_fields({"decor_choice": "sticker"}) == {}


def test_validate_coerces_quantity_to_int_or_drops_it():
    assert ie.validate_fields({"quantity": 50}) == {"quantity": 50}
    assert ie.validate_fields({"quantity": "50"}) == {"quantity": 50}
    assert ie.validate_fields({"quantity": "loads"}) == {}


@pytest.mark.asyncio
async def test_interpret_raises_when_no_key(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", False)
    with pytest.raises(ie.LLMUnavailable):
        await ie.interpret_turn_v2(cs.by_id(S.ASK_ANOTHER_LOGO), "go on then", {})


@pytest.mark.asyncio
async def test_interpret_raises_when_the_call_fails(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)

    async def _boom(*a, **k):
        raise RuntimeError("429")

    monkeypatch.setattr(ie, "_complete", _boom)
    with pytest.raises(ie.LLMUnavailable):
        await ie.interpret_turn_v2(cs.by_id(S.ASK_ANOTHER_LOGO), "go on then", {})


@pytest.mark.asyncio
async def test_interpret_returns_validated_fields(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)

    async def _ok(*a, **k):
        return '{"fields": {"another_logo": true, "quantity": 50, "logos": ["x"]}}'

    monkeypatch.setattr(ie, "_complete", _ok)
    got = await ie.interpret_turn_v2(cs.by_id(S.ASK_ANOTHER_LOGO), "yeah and 50 caps", {})
    # Volunteered quantity is banked (that is where reordering comes from);
    # the internal `logos` key is dropped.
    assert got == {"another_logo": True, "quantity": 50}


@pytest.mark.asyncio
async def test_interpret_never_sends_pii(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)
    seen = {}

    async def _spy(prompt, **k):
        seen["prompt"] = prompt
        return '{"fields": {}}'

    monkeypatch.setattr(ie, "_complete", _spy)
    await ie.interpret_turn_v2(cs.by_id(S.ASK_QUANTITY), "50",
                               {"name": "Sam", "email": "sam@example.com"})
    assert "sam@example.com" not in seen["prompt"]


@pytest.mark.asyncio
async def test_write_ack_never_sends_an_email_to_the_model(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)
    seen = {}

    async def _spy(prompt, **k):
        seen["prompt"] = prompt
        return "Got it."

    monkeypatch.setattr(ie, "_complete", _spy)
    await ie.write_ack("Ricardo", {"email": "sam@example.com", "quantity": 50})
    assert "sam@example.com" not in seen["prompt"]
    assert "50" in seen["prompt"]          # non-PII substance still reaches it


@pytest.mark.asyncio
async def test_write_ack_skips_the_model_when_only_pii_was_captured(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)
    calls = []

    async def _spy(prompt, **k):
        calls.append(1)
        return "x"

    monkeypatch.setattr(ie, "_complete", _spy)
    assert await ie.write_ack("Ricardo", {"email": "sam@example.com"}) == ""
    assert calls == []                     # nothing non-PII left -> no call at all


@pytest.mark.asyncio
async def test_write_ack_returns_empty_on_failure(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)

    async def _boom(*a, **k):
        raise RuntimeError("429")

    monkeypatch.setattr(ie, "_complete", _boom)
    # Best-effort by design: an outage makes the bot terse, never uninstructive.
    assert await ie.write_ack("Ricardo", {"quantity": 50}) == ""
