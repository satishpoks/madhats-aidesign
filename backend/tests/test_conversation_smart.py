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


# ---------------------------------------------------------------------------
# Orchestrator: interpreter-first turn, side-questions, progress
# ---------------------------------------------------------------------------

from app.services.conversation import orchestrator as orch
from app.services.conversation.state_machine import ConversationState as S


class _FakeTable:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self._filters = {}

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, *_):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        if self.name == "design_sessions":
            return type("R", (), {"data": [self.store["session"]]})()
        return type("R", (), {"data": []})()

    def update(self, patch):
        self.store["session"].update(patch)
        return self

    def insert(self, rows):
        return self


class _FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeTable(self.store, name)


@pytest.mark.asyncio
async def test_progress_is_returned_each_turn(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_QUANTITY.value, "collected": {"name": "Al"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {"quantity": 20}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("ok"))
    res = await orch.handle_message("s1", "20")
    assert "progress" in res["data"]
    assert res["data"]["progress"]["total"] >= 1


@pytest.mark.asyncio
async def test_side_question_does_not_advance(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_QUANTITY.value, "collected": {"name": "Al"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(
        orch.ie, "interpret_turn",
        _fixed_interpret({"intent": "ask_question", "fields": {}, "question_answer": "Embroidery lasts longer."}),
    )
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("re-ask"))
    res = await orch.handle_message("s1", "which lasts longer?")
    assert res["state"] == S.ASK_QUANTITY.value  # stayed put


def _fixed_interpret(payload):
    base = {"intent": "answer", "fields": {}, "revise_target": None,
            "backtrack_target": None, "question_answer": "", "on_topic": True}
    base.update(payload)

    async def _f(*a, **k):
        return dict(base)

    return _f


def _fixed_reply(text):
    async def _f(*a, **k):
        return text
    return _f


def _fake_settings():
    """Return a get_settings() stand-in with an empty FAQ (no Supabase hit)."""
    def _f():
        return type("S", (), {"faq_knowledge": ""})()
    return _f


@pytest.mark.asyncio
async def test_upload_logo_chip_advances_even_if_misclassified(monkeypatch):
    # Regression: the has-logo step used to loop when the interpreter tagged the
    # chip tap as a question. A chip answer must always advance to the uploader.
    store = {"session": {"id": "s1", "state": S.ASK_HAS_LOGO.value, "collected": {"name": "Al"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(
        orch.ie, "interpret_turn",
        _fixed_interpret({"intent": "ask_question", "fields": {}, "question_answer": "..."}),
    )
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("upload please"))
    res = await orch.handle_message("s1", "Upload logo")
    assert res["state"] == S.UPLOAD_LOGO.value


@pytest.mark.asyncio
async def test_describe_chip_routes_to_describe(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_HAS_LOGO.value, "collected": {"name": "Al"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("describe please"))
    res = await orch.handle_message("s1", "Describe what I want")
    assert res["state"] == S.DESCRIBE_DESIGN.value


@pytest.mark.asyncio
async def test_typed_have_a_logo_reaches_upload(monkeypatch):
    # Deterministic has_logo derivation: even when the interpreter omits has_logo,
    # a typed "I have a logo" must reach the upload step (not the describe path).
    store = {"session": {"id": "s1", "state": S.ASK_HAS_LOGO.value, "collected": {"name": "Al"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("ok"))
    res = await orch.handle_message("s1", "yes I have a logo ready")
    assert res["state"] == S.UPLOAD_LOGO.value
