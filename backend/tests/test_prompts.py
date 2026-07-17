import pytest

from app import prompts
from app.services.conversation import intent_extractor as ie


def test_gather_states_have_copy():
    for slug in ("ask_more_elements", "add_elements_mode"):
        assert slug in prompts.CANNED_REPLIES
        assert slug in prompts.STATE_PROMPTS
    # Goal-leading: the offer names concrete element types and an exit.
    assert "text" in prompts.CANNED_REPLIES["ask_more_elements"].lower()


def test_deepdive_states_have_copy():
    for slug in ("ask_more_elements", "element_deepdive"):
        assert slug in prompts.CANNED_REPLIES
        assert slug in prompts.STATE_PROMPTS
    assert "graphic" in prompts.CANNED_REPLIES["ask_more_elements"].lower()


def test_new_state_copy_present():
    for key in ("ask_hat_colour", "composite_preview"):
        assert key in prompts.STATE_PROMPTS
        assert key in prompts.CANNED_REPLIES


def test_confirm_canvas_edit_has_copy_in_both_dicts():
    # Sibling ASK_CHANGE_METHOD (same feature) has entries in both dicts —
    # CONFIRM_CANVAS_EDIT must too, or the gate shows filler instead of
    # confirming the change + asking if it looks right.
    assert "confirm_canvas_edit" in prompts.STATE_PROMPTS
    assert "confirm_canvas_edit" in prompts.CANNED_REPLIES

    canned = prompts.CANNED_REPLIES["confirm_canvas_edit"].lower()
    # Must describe the change as visible on the design now, not as sent/rendered.
    assert "render" not in canned
    assert "email" not in canned
    assert "inbox" not in canned
    # Must ask whether it looks right.
    assert "look" in canned


@pytest.mark.asyncio
async def test_confirm_canvas_edit_canned_reply_is_not_the_generic_fallback(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", False)
    out = await ie.generate_reply("confirm_canvas_edit", {}, "Ricardo")
    assert out != "Let's keep going — what would you like to do next?"
    assert out == prompts.CANNED_REPLIES["confirm_canvas_edit"]
