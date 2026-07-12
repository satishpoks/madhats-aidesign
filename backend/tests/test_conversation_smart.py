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
async def test_bare_name_advances_and_is_not_reasked(monkeypatch):
    # Regression: a bare first name must be captured and the flow must move to
    # purpose — never ask the name a second time.
    store = {"session": {"id": "s1", "state": S.ASK_NAME.value, "collected": {}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    # Interpreter misclassifies the bare word as chitchat with no fields.
    monkeypatch.setattr(
        orch.ie, "interpret_turn",
        _fixed_interpret({"intent": "chitchat", "fields": {}}),
    )
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("what are they for?"))
    res = await orch.handle_message("s1", "Satish")
    assert store["session"]["collected"]["name"] == "Satish"
    assert res["state"] == S.ASK_PURPOSE.value


@pytest.mark.asyncio
async def test_side_question_does_not_advance(monkeypatch):
    # A pure question at an unmet slot is answered but stays on that slot.
    store = {"session": {"id": "s1", "state": S.ASK_QUANTITY.value,
                         "collected": {"name": "Al", "purpose": "gifts"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(
        orch.ie, "interpret_turn",
        _fixed_interpret({"intent": "ask_question", "fields": {}, "question_answer": "Embroidery lasts longer."}),
    )
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("re-ask"))
    res = await orch.handle_message("s1", "which lasts longer?")
    assert res["state"] == S.ASK_QUANTITY.value  # quantity still unmet -> stays


@pytest.mark.asyncio
async def test_upload_logo_chip_advances_even_if_misclassified(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_HAS_LOGO.value,
                         "collected": {"name": "Al", "purpose": "gifts", "quantity": 24,
                                       "decoration_type": "embroidery"}, "upsell_count": 0}}
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
    store = {"session": {"id": "s1", "state": S.ASK_HAS_LOGO.value,
                         "collected": {"name": "Al", "purpose": "gifts", "quantity": 24,
                                       "decoration_type": "embroidery"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("describe please"))
    res = await orch.handle_message("s1", "Describe what I want")
    assert res["state"] == S.DESCRIBE_DESIGN.value


@pytest.mark.asyncio
async def test_typed_have_a_logo_reaches_upload(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_HAS_LOGO.value,
                         "collected": {"name": "Al", "purpose": "gifts", "quantity": 24,
                                       "decoration_type": "embroidery"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("ok"))
    res = await orch.handle_message("s1", "yes I have a logo ready")
    assert res["state"] == S.UPLOAD_LOGO.value


@pytest.mark.asyncio
async def test_placement_zone_defaults_position_and_skips_position_turn(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_PLACEMENT_ZONE.value,
                         "collected": {"name": "Al", "purpose": "gifts", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements": [{"type": "text", "content": "x"}],
                                       "elements_offered": True, "email_prompt_shown": True},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(
        orch.ie, "interpret_turn",
        _fixed_interpret({"intent": "answer", "fields": {"placement_zone": "front_panel"}}),
    )
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("pin?"))
    res = await orch.handle_message("s1", "front panel")
    assert store["session"]["collected"]["placement_position"] == "centre"
    # position turn skipped -> pin is hidden, so next is generation
    assert res["state"] == S.GENERATING.value


@pytest.mark.asyncio
async def test_more_elements_yes_enters_add_mode(monkeypatch):
    # Rewritten for Task 5: a type choice at ASK_MORE_ELEMENTS seeds a
    # pending_element and routes into the per-element deep-dive (there is no
    # more ADD_ELEMENTS_MODE hop).
    store = {"session": {"id": "s1", "state": S.ASK_MORE_ELEMENTS.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements": [{"type": "text", "content": "TEAM"}],
                                       "elements_offered": True}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("what would you like to add?"))
    res = await orch.handle_message("s1", "Add text")
    assert res["state"] == S.ELEMENT_DEEPDIVE.value
    assert store["session"]["collected"]["pending_element"]["type"] == "text"


@pytest.mark.asyncio
async def test_more_elements_decline_goes_to_generating(monkeypatch):
    # Pin placement is hidden: a decline at ASK_MORE_ELEMENTS with no pending
    # element goes straight to generation.
    store = {"session": {"id": "s1", "state": S.ASK_MORE_ELEMENTS.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements": [{"type": "text", "content": "TEAM"}],
                                       "elements_offered": True}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("mark a spot?"))
    res = await orch.handle_message("s1", "That's everything")
    assert res["state"] == S.GENERATING.value
    assert "pending_element" not in store["session"]["collected"] or not store["session"]["collected"]["pending_element"]


@pytest.mark.asyncio
async def test_add_mode_exits_on_done(monkeypatch):
    # Rewritten for Task 5: the per-element "done" signal (previously
    # ADD_ELEMENTS_MODE's exit) now completes the CURRENT pending element via
    # element_planner.defer_remaining and routes back to ASK_MORE_ELEMENTS.
    pend = {"type": "text", "content": "TEAM", "deferred": []}
    store = {"session": {"id": "s1", "state": S.ELEMENT_DEEPDIVE.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements": [], "elements_offered": True,
                                       "pending_element": pend}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("placing it"))
    res = await orch.handle_message("s1", "that's it, generate")
    assert res["state"] == S.ASK_MORE_ELEMENTS.value
    c = store["session"]["collected"]
    assert c["elements"][-1]["content"] == "TEAM"
    assert "pending_element" not in c or not c["pending_element"]


def test_public_data_offers_element_chips():
    data = orch._public_data(S.ASK_MORE_ELEMENTS, {})
    assert "That's everything" in data["options"]


def test_more_elements_offers_all_types():
    opts = orch._public_data(S.ASK_MORE_ELEMENTS, {})["options"]
    assert opts == ["Add text", "Add a graphic", "Add a note", "That's everything"]


def test_deepdive_placement_chips_include_you_choose():
    data = orch._public_data(S.ELEMENT_DEEPDIVE, {"deepdive_ask_for": "placement_zone"})
    assert "Front panel" in data["options"]
    assert "You choose" in data["options"]


def test_deepdive_content_has_no_you_choose():
    data = orch._public_data(S.ELEMENT_DEEPDIVE, {"deepdive_ask_for": "content"})
    assert data.get("options", []) == []  # free text only; content is required


# ---------------------------------------------------------------------------
# Orchestrator: per-element lifecycle + deep-dive routing (Task 5)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_graphic_records_graphic_type_not_text(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_MORE_ELEMENTS.value,
        "collected": {"name": "Al", "purpose": "p", "quantity": 24, "decoration_type": "embroidery",
                     "has_logo": False, "elements": [{"type": "text", "content": "TEAM"}],
                     "elements_offered": True}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("describe the graphic"))
    res = await orch.handle_message("s1", "Add a graphic")
    assert res["state"] == S.ELEMENT_DEEPDIVE.value
    assert store["session"]["collected"]["pending_element"]["type"] == "graphic"


@pytest.mark.asyncio
async def test_deepdive_captures_then_completes_and_appends(monkeypatch):
    pend = {"type": "text", "content": "TEAM", "font": "bold", "size": "large", "colour": "gold",
            "style": "none", "placement_zone": "front_panel", "deferred": []}
    store = {"session": {"id": "s1", "state": S.ELEMENT_DEEPDIVE.value,
        "collected": {"name": "Al", "quantity": 24, "decoration_type": "embroidery", "has_logo": False,
                     "elements": [], "elements_offered": True, "pending_element": pend},
        "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    async def _attrs(t, m): return {"placement_position": "centre"}
    monkeypatch.setattr(orch.ie, "extract_element_attributes", _attrs)
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("anything else?"))
    res = await orch.handle_message("s1", "centre")
    c = store["session"]["collected"]
    assert c["elements"][-1]["content"] == "TEAM"        # completed element pushed
    assert "pending_element" not in c or not c["pending_element"]
    assert res["state"] == S.ASK_MORE_ELEMENTS.value


@pytest.mark.asyncio
async def test_defer_marks_attribute_and_moves_on(monkeypatch):
    pend = {"type": "text", "content": "TEAM", "deferred": []}
    store = {"session": {"id": "s1", "state": S.ELEMENT_DEEPDIVE.value,
        "collected": {"name": "Al", "quantity": 24, "decoration_type": "embroidery", "has_logo": False,
                     "elements": [], "elements_offered": True, "pending_element": pend,
                     "deepdive_ask_for": "font"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    async def _attrs(t, m): return {"defer": True}
    monkeypatch.setattr(orch.ie, "extract_element_attributes", _attrs)
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("size?"))
    await orch.handle_message("s1", "you choose")
    el = store["session"]["collected"]["pending_element"]
    assert "font" in el["deferred"]
    # Finding 3 (Minor): a defer must ONLY append to `deferred` — the
    # raw-message fallback must not also write "you choose" (or anything
    # else) into el["font"] on the same turn.
    assert not el.get("font")


@pytest.mark.asyncio
async def test_deepdive_remove_bg_not_flipped_by_later_turn(monkeypatch):
    # Regression: the no-key `remove_bg` heuristic matches bare
    # "yes"/"no"/"keep"/"leave" filler words that show up in unrelated
    # answers (e.g. "Medium, no rush"). Once remove_bg is already answered,
    # a LATER turn answering a different attribute must not let a stray
    # heuristic re-match silently flip it back.
    pend = {"type": "logo", "asset_path": "x.png", "content": "uploaded logo",
            "remove_bg": True, "deferred": []}
    store = {"session": {"id": "s1", "state": S.ELEMENT_DEEPDIVE.value,
        "collected": {"name": "Al", "quantity": 24, "decoration_type": "embroidery", "has_logo": True,
                     "elements": [], "elements_offered": True, "pending_element": pend,
                     "deepdive_ask_for": "size"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))

    async def _attrs(t, m):
        return {"size": "medium", "remove_bg": False}  # simulates the stray heuristic match

    monkeypatch.setattr(orch.ie, "extract_element_attributes", _attrs)
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("placement?"))
    await orch.handle_message("s1", "Medium, no rush")
    el = store["session"]["collected"]["pending_element"]
    assert el["remove_bg"] is True   # not flipped by the unrelated turn
    assert el["size"] == "medium"    # the real answer is still captured


@pytest.mark.asyncio
async def test_deepdive_remove_bg_captured_when_actually_asked(monkeypatch):
    pend = {"type": "logo", "asset_path": "x.png", "content": "uploaded logo", "deferred": []}
    store = {"session": {"id": "s1", "state": S.ELEMENT_DEEPDIVE.value,
        "collected": {"name": "Al", "quantity": 24, "decoration_type": "embroidery", "has_logo": True,
                     "elements": [], "elements_offered": True, "pending_element": pend,
                     "deepdive_ask_for": "remove_bg"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))

    async def _attrs(t, m):
        return {"remove_bg": False}

    monkeypatch.setattr(orch.ie, "extract_element_attributes", _attrs)
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("size?"))
    await orch.handle_message("s1", "No, keep as-is")
    el = store["session"]["collected"]["pending_element"]
    assert el["remove_bg"] is False


# ---------------------------------------------------------------------------
# Orchestrator: structured design brief accumulation (Task 6)
# ---------------------------------------------------------------------------

def _capture_extractor(mapping):
    """Fake extract_design_description returning a structured dict per message."""
    async def _f(message):
        return mapping.get(message, {"summary": message})
    return _f


@pytest.mark.asyncio
async def test_add_mode_no_longer_populates_flat_brief(monkeypatch):
    # Updated for Task 5: ADD_ELEMENTS_MODE's gather-loop is retired — removing
    # the wants_more_elements/add_another_element derivations means
    # _maybe_gather_element's gate for this state is never satisfied anymore,
    # so it no longer accumulates into the flat design_description brief.
    # Elements are now captured via the pending_element/ELEMENT_DEEPDIVE
    # lifecycle instead (see test_add_graphic_records_graphic_type_not_text
    # and friends above).
    calls = []
    async def _spy(message):
        calls.append(message)
        return {"text_elements": ["SUMMIT CO"], "colours": ["gold"]}
    store = {"session": {"id": "s1", "state": S.ADD_ELEMENTS_MODE.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements_offered": True,
                                       "design_description": {"summary": "a mountain crest"}},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("added"))
    monkeypatch.setattr(orch.ie, "extract_design_description", _spy)
    await orch.handle_message("s1", "add SUMMIT CO in gold")
    brief = store["session"]["collected"]["design_description"]
    assert brief == {"summary": "a mountain crest"}      # unchanged — flat-brief gather retired
    assert calls == []


@pytest.mark.asyncio
async def test_decline_does_not_extract(monkeypatch):
    calls = []
    async def _spy(message):
        calls.append(message)
        return {"summary": message}
    store = {"session": {"id": "s1", "state": S.ASK_MORE_ELEMENTS.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements_offered": True,
                                       "design_description": {"summary": "a crest"}},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("ok"))
    monkeypatch.setattr(orch.ie, "extract_design_description", _spy)
    await orch.handle_message("s1", "That's everything")
    assert calls == []  # a decline carries no element to extract


@pytest.mark.asyncio
async def test_bare_yes_in_add_mode_does_not_extract(monkeypatch):
    calls = []
    async def _spy(message):
        calls.append(message)
        return {"summary": message}
    store = {"session": {"id": "s1", "state": S.ADD_ELEMENTS_MODE.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements_offered": True,
                                       "design_description": {"summary": "a crest"}},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("ok"))
    monkeypatch.setattr(orch.ie, "extract_design_description", _spy)
    res = await orch.handle_message("s1", "yes")
    assert calls == []  # a bare ack carries no element to extract
    assert res["state"] == S.ADD_ELEMENTS_MODE.value  # loop keeps gathering


@pytest.mark.asyncio
async def test_refinement_add_updates_brief(monkeypatch):
    store = {"session": {"id": "s1", "state": S.DESCRIBE_CHANGES.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements_offered": True, "placement_zone": "front_panel",
                                       "design_description": {"summary": "a crest"}},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("updating"))
    monkeypatch.setattr(
        orch.ie, "extract_design_description",
        _capture_extractor({"add our team name in gold": {"text_elements": ["team name"], "colours": ["gold"]}}),
    )
    await orch.handle_message("s1", "add our team name in gold")
    collected = store["session"]["collected"]
    assert "team name" in collected["design_description"]["text_elements"]
    assert collected["last_change"] == "add our team name in gold"  # raw change still set


@pytest.mark.asyncio
async def test_refinement_freeform_edit_does_not_leak_into_brief(monkeypatch):
    # Regression (Finding 1): a non-additive edit ("make the logo bigger") must
    # NOT be promoted into the structured brief's text_elements — it would then
    # render onto the cap literally via the prompt builder. The raw instruction
    # still flows through `last_change` / `change_request`, just not the brief.
    store = {"session": {"id": "s1", "state": S.DESCRIBE_CHANGES.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements_offered": True, "placement_zone": "front_panel",
                                       "design_description": {"summary": "a crest"}},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("updating"))
    monkeypatch.setattr(
        orch.ie, "extract_design_description",
        _capture_extractor({"make the logo bigger": {"summary": "make the logo bigger"}}),
    )
    await orch.handle_message("s1", "make the logo bigger")
    collected = store["session"]["collected"]
    text_elements = collected["design_description"].get("text_elements", [])
    assert "make the logo bigger" not in text_elements
    assert collected["design_description"] == {"summary": "a crest"}  # brief unchanged
    assert collected["last_change"] == "make the logo bigger"


@pytest.mark.asyncio
async def test_refinement_malformed_empty_list_does_not_leak_into_brief(monkeypatch):
    # Regression (whole-branch re-review): a malformed extractor result whose
    # `text_elements` is a non-empty LIST containing only an empty string
    # (e.g. [""]) must not satisfy `_is_structured_element` via bare list
    # truthiness — that would bypass the DESCRIBE_CHANGES guard and let the
    # freeform edit "make the logo bigger" leak into text_elements, same as
    # the bare-summary case above. `_is_structured_element` must require a
    # real (non-empty) item in the list, mirroring `brief.has_incoming_lists`.
    store = {"session": {"id": "s1", "state": S.DESCRIBE_CHANGES.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements_offered": True, "placement_zone": "front_panel",
                                       "design_description": {"summary": "a crest"}},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("updating"))
    monkeypatch.setattr(
        orch.ie, "extract_design_description",
        _capture_extractor({"make the logo bigger": {"text_elements": [""], "summary": "make the logo bigger"}}),
    )
    await orch.handle_message("s1", "make the logo bigger")
    collected = store["session"]["collected"]
    text_elements = collected["design_description"].get("text_elements", [])
    assert "make the logo bigger" not in text_elements
    assert collected["last_change"] == "make the logo bigger"


@pytest.mark.asyncio
async def test_already_have_logo_is_not_treated_as_decline(monkeypatch):
    # Regression (Finding 2), rewritten for Task 5: "already" must not
    # substring-match "ready" in _DONE_ELEMENTS — "already have the logo, also
    # add a star" is NOT a decline. It should detect an element type (the word
    # "logo" -> graphic) and enter the per-element deep-dive, not be dropped
    # as though the customer declined further elements.
    store = {"session": {"id": "s1", "state": S.ASK_MORE_ELEMENTS.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements": [{"type": "text", "content": "TEAM"}],
                                       "elements_offered": True}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("what would you like to add?"))
    # This message is more than the bare type keyword, so (Finding 5) it now
    # runs one extract_element_attributes pass to capture any volunteered
    # content along with the type choice -- mock it so the test stays
    # hermetic (no real LLM call) regardless of local .env key configuration.
    async def _attrs(t, m): return {}
    monkeypatch.setattr(orch.ie, "extract_element_attributes", _attrs)
    res = await orch.handle_message("s1", "already have the logo, also add a star")
    assert res["state"] == S.ELEMENT_DEEPDIVE.value
    assert store["session"]["collected"]["pending_element"]["type"] == "graphic"


@pytest.mark.asyncio
async def test_type_choice_with_content_captures_volunteered_content(monkeypatch):
    # Finding 5 (whole-branch review): "add text saying GO TEAM" at
    # ASK_MORE_ELEMENTS must not discard "GO TEAM" -- seeding pending_element
    # from the bare type ("text") alone would force a redundant re-ask of
    # content on the very next turn even though the customer already gave it.
    store = {"session": {"id": "s1", "state": S.ASK_MORE_ELEMENTS.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements": [], "elements_offered": True}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))

    async def _attrs(t, m):
        return {"content": "GO TEAM"}

    monkeypatch.setattr(orch.ie, "extract_element_attributes", _attrs)
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("got it, anything else about it?"))
    res = await orch.handle_message("s1", "add text saying GO TEAM")
    pend = store["session"]["collected"]["pending_element"]
    assert pend["content"] == "GO TEAM"
    assert res["state"] == S.ELEMENT_DEEPDIVE.value
    assert store["session"]["collected"].get("deepdive_ask_for") != "content"


@pytest.mark.asyncio
async def test_bare_type_chip_does_not_call_extractor(monkeypatch):
    # The plain "Add text" chip (Figma option) must keep just seeding the type
    # and asking content next -- it must NOT trigger an extraction call.
    calls = []
    store = {"session": {"id": "s1", "state": S.ASK_MORE_ELEMENTS.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements": [], "elements_offered": True}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))

    async def _attrs(t, m):
        calls.append(m)
        return {}

    monkeypatch.setattr(orch.ie, "extract_element_attributes", _attrs)
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("what should it say?"))
    res = await orch.handle_message("s1", "Add text")
    assert calls == []
    assert store["session"]["collected"]["pending_element"] == {"type": "text", "deferred": []}
    assert res["state"] == S.ELEMENT_DEEPDIVE.value


# ---------------------------------------------------------------------------
# Per-element attribute extraction + dynamic ask_for reply wording (Task 4)
# ---------------------------------------------------------------------------

from app.services.conversation import intent_extractor as ie2


@pytest.mark.asyncio
async def test_extract_attributes_no_key_detects_defer_and_zone(monkeypatch):
    monkeypatch.setattr(ie2, "_has_llm", False)
    out = await ie2.extract_element_attributes("text", "you choose the font")
    assert out.get("defer") is True
    out2 = await ie2.extract_element_attributes("graphic", "put it on the left side")
    assert out2.get("placement_zone") == "side"


@pytest.mark.asyncio
async def test_extract_attributes_no_key_detects_remove_bg_yes_no(monkeypatch):
    # Finding 1: without an API key, a logo element's first attribute
    # (remove_bg) must be answerable, or the deep-dive re-asks it forever —
    # only "you choose" (defer) could escape before this fix.
    monkeypatch.setattr(ie2, "_has_llm", False)
    out = await ie2.extract_element_attributes("logo", "Yes, remove it")
    assert out == {"remove_bg": True}
    out2 = await ie2.extract_element_attributes("logo", "No, keep as-is")
    assert out2 == {"remove_bg": False}


@pytest.mark.asyncio
async def test_extract_attributes_no_key_company_not_treated_as_defer(monkeypatch):
    monkeypatch.setattr(ie2, "_has_llm", False)
    out = await ie2.extract_element_attributes("text", "add our company name in bold")
    assert not out.get("defer")


@pytest.mark.asyncio
async def test_generate_reply_ask_for_no_key_uses_attribute_question(monkeypatch):
    monkeypatch.setattr(ie2, "_has_llm", False)
    reply = await ie2.generate_reply("element_deepdive", {"pending_element": {"type": "text"}},
                                     "Ricardo", ask_for="font")
    assert "font" in reply.lower()


@pytest.mark.asyncio
async def test_describe_design_first_turn_enters_deepdive(monkeypatch):
    # Finding 1 (CRITICAL): the first element (described design or uploaded
    # logo) must not skip its deep-dive. DESCRIBE_DESIGN is not a gate state,
    # so `_route` sends the turn through `goal_planner.next_goal` on the same
    # turn `_advance_elements` seeds `pending_element` -- without the planner
    # fix this falls through to ASK_MORE_ELEMENTS and the customer's next
    # reply (meant to answer the deep-dive) is silently dropped.
    store = {"session": {"id": "s1", "state": S.DESCRIBE_DESIGN.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "email_prompt_shown": True},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    async def _attrs(t, m): return {}
    monkeypatch.setattr(orch.ie, "extract_element_attributes", _attrs)
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("tell me more"))
    res = await orch.handle_message("s1", "a mountain crest logo")
    assert res["state"] == S.ELEMENT_DEEPDIVE.value
    pend = store["session"]["collected"]["pending_element"]
    assert pend["type"] in ("text", "graphic")
    assert pend["content"]


@pytest.mark.asyncio
async def test_describe_design_does_not_double_extract_flat_brief(monkeypatch):
    # Finding 2 (Moderate) / Finding 4 (whole-branch review): DESCRIBE_DESIGN
    # must no longer be an `_ELEMENT_STATES` member -- the element lifecycle
    # (`_advance_elements`) owns it now, and the old flat-brief path
    # (`_maybe_gather_element` -> `extract_design_description`) must not also
    # run on the same turn. `fields` here is the REAL no-key volunteered shape
    # (`_extract_fields_for_state("describe_design", ...)` sets
    # `fields["design_description"]`) -- the previous version of this test
    # passed `fields={}`, which only worked because it never exercised the
    # `volunteered` branch `_maybe_gather_element` actually guards against.
    store = {"session": {"id": "s1", "state": S.DESCRIBE_DESIGN.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(
        orch.ie, "interpret_turn",
        _fixed_interpret({"intent": "answer", "fields": {"design_description": {"summary": "a mountain crest logo"}}}),
    )
    async def _attrs(t, m): return {}
    monkeypatch.setattr(orch.ie, "extract_element_attributes", _attrs)
    calls = []
    async def _spy(message):
        calls.append(message)
        return {"text_elements": ["mountain crest"]}
    monkeypatch.setattr(orch.ie, "extract_design_description", _spy)
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("tell me more"))
    await orch.handle_message("s1", "a mountain crest logo")
    assert calls == []
    assert "design_description" not in store["session"]["collected"]


@pytest.mark.asyncio
async def test_verification_lands_on_offer_refine_with_ack(monkeypatch):
    store = {"session": {"id": "s1", "state": S.VERIFY_EMAIL.value,
                         "collected": {"name": "Al", "email_verified": True},
                         "upsell_count": 0, "store_id": None}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())

    captured = {}
    async def _reply(state, collected, persona, aside=None):
        captured["state"] = state
        captured["aside"] = aside
        return "worded"
    monkeypatch.setattr(orch.ie, "generate_reply", _reply)

    res = await orch.check_verification("s1")
    assert res["state"] == S.OFFER_REFINE.value       # collapsed, no redundant taps
    assert captured["state"] == S.OFFER_REFINE.value
    assert captured["aside"] and "verified" in captured["aside"].lower()


@pytest.mark.asyncio
async def test_save_progress_email_captures_and_continues(monkeypatch):
    # A valid email at SAVE_PROGRESS_EMAIL is captured (verification sent) and
    # the flow continues into the deep-dive — non-blocking.
    pend = {"type": "text", "content": "TEAM", "deferred": []}
    store = {"session": {"id": "s1", "state": S.SAVE_PROGRESS_EMAIL.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "pending_element": pend, "email_prompt_shown": True},
                         "store_id": None, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("great, saved!"))
    monkeypatch.setattr(orch.leads_service, "extract_email", lambda m: "al@example.com")
    captured = {}
    def _cap(session, collected, email):
        captured["email"] = email
        return "lead-123"
    monkeypatch.setattr(orch.leads_service, "capture_lead_and_verify", _cap)

    res = await orch.handle_message("s1", "al@example.com")
    c = store["session"]["collected"]
    assert captured["email"] == "al@example.com"
    assert c["email_captured"] is True
    assert c["lead_id"] == "lead-123"
    # non-blocking: continues into the deep-dive (pending element still building)
    assert res["state"] == S.ELEMENT_DEEPDIVE.value


@pytest.mark.asyncio
async def test_save_progress_email_no_email_still_continues(monkeypatch):
    # A non-email reply doesn't dead-end: email_prompt_shown stays set and the
    # flow proceeds to the deep-dive without capturing.
    pend = {"type": "text", "content": "TEAM", "deferred": []}
    store = {"session": {"id": "s1", "state": S.SAVE_PROGRESS_EMAIL.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "pending_element": pend, "email_prompt_shown": True},
                         "store_id": None, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("no worries"))
    monkeypatch.setattr(orch.leads_service, "extract_email", lambda m: None)

    res = await orch.handle_message("s1", "maybe later")
    c = store["session"]["collected"]
    assert not c.get("email_captured")
    assert res["state"] == S.ELEMENT_DEEPDIVE.value
