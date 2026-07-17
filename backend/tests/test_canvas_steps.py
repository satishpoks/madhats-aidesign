from app.services.conversation import canvas_steps as cs
from app.services.conversation.state_machine import ConversationState as S


def test_registry_ids_are_unique_and_are_conversation_states():
    ids = [s.id for s in cs.REGISTRY]
    assert len(ids) == len(set(ids))
    assert all(isinstance(i, S) for i in ids)


def test_registry_declares_the_v2_flow_in_order():
    assert [s.id for s in cs.REGISTRY] == [
        S.ASK_NAME, S.SHOW_INTRO,
        S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST, S.ASK_ANOTHER_LOGO,
        S.ASK_ADD_DECOR, S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE,
        S.ASK_QUANTITY, S.ASK_EMAIL, S.ASK_PURPOSE, S.FINALIZE_CANVAS,
    ]


def test_ask_email_precedes_finalize():
    ids = [s.id for s in cs.REGISTRY]
    assert ids.index(S.ASK_EMAIL) < ids.index(S.FINALIZE_CANVAS)


def test_chips_may_set_slots_plus_trusted_flags_the_llm_cannot():
    # Chips are trusted (we authored the label AND its fields), so they may set
    # terminal/annotation flags that are deliberately NOT in the interpreter's
    # writable set — the model must never be able to declare the decor loop over
    # or fake a "not sure".
    allowed = cs.WRITABLE_SLOTS | {"decor_done", "quantity_unsure"}
    for step in cs.REGISTRY:
        for chip in step.chips:
            assert set(chip.fields) <= allowed, f"{step.id}: {chip.label}"


def test_terminal_flags_are_not_interpreter_writable():
    assert "decor_done" not in cs.WRITABLE_SLOTS
    assert "quantity_unsure" not in cs.WRITABLE_SLOTS
    assert "email_captured" not in cs.WRITABLE_SLOTS


def test_tool_steps_carry_a_tip_and_tipless_steps_carry_no_tool():
    for step in cs.REGISTRY:
        assert bool(step.tool) == bool(step.tip), step.id


def test_by_id_round_trips():
    assert cs.by_id(S.ASK_ANOTHER_LOGO).id is S.ASK_ANOTHER_LOGO
    assert cs.by_id(S.OFFER_REFINE) is None      # a shared-tail state v2 doesn't own
