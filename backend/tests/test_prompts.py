from app import prompts


def test_gather_states_have_copy():
    for slug in ("ask_more_elements", "add_elements_mode"):
        assert slug in prompts.CANNED_REPLIES
        assert slug in prompts.STATE_PROMPTS
    # Goal-leading: the offer names concrete element types and an exit.
    assert "text" in prompts.CANNED_REPLIES["ask_more_elements"].lower()
