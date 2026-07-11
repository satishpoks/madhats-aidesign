import pytest

from app.services.conversation import intent_extractor as ie


@pytest.mark.asyncio
async def test_interpret_turn_heuristic_extracts_current_field(monkeypatch):
    # No API key -> deterministic fallback: answer-only, current-field extraction.
    monkeypatch.setattr(ie, "_has_llm", False)
    out = await ie.interpret_turn(
        "ask_quantity", "about 50 hats", {}, [], ""
    )
    assert out["intent"] == "answer"
    assert out["fields"]["quantity"] == 50
    assert out["question_answer"] == ""


@pytest.mark.asyncio
async def test_interpret_turn_uses_llm_json_when_available(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)

    async def fake_complete(prompt, **kw):
        return (
            '{"intent":"provide_info","fields":{"quantity":50,'
            '"placement_zone":"front_panel"},"revise_target":null,'
            '"backtrack_target":null,"question_answer":"","on_topic":true}'
        )

    monkeypatch.setattr(ie, "_complete", fake_complete)
    out = await ie.interpret_turn("ask_quantity", "50 on the front", {}, [], "")
    assert out["intent"] == "provide_info"
    assert out["fields"]["placement_zone"] == "front_panel"


@pytest.mark.asyncio
async def test_interpret_turn_normalizes_missing_keys(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)

    async def fake_complete(prompt, **kw):
        return '{"intent":"chitchat"}'

    monkeypatch.setattr(ie, "_complete", fake_complete)
    out = await ie.interpret_turn("ask_name", "how's your day?", {}, [], "")
    assert out["intent"] == "chitchat"
    assert out["fields"] == {}
    assert out["backtrack_target"] is None
