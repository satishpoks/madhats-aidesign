from app import prompts


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
