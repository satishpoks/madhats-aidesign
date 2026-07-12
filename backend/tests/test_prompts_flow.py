"""Copy + enum guards for the early-email / hidden-pin flow changes."""
from app.prompts import CANNED_REPLIES, STATE_PROMPTS
from app.services.conversation.state_machine import ConversationState as S


def test_save_progress_email_state_exists():
    assert S.SAVE_PROGRESS_EMAIL.value == "save_progress_email"


def test_save_progress_email_copy_mentions_progress():
    canned = CANNED_REPLIES["save_progress_email"].lower()
    assert "progress" in canned
    assert "email" in canned or "@" in canned
    assert "save_progress_email" in STATE_PROMPTS


def test_generating_copy_no_longer_asks_for_email():
    # Email is captured earlier now; the generating line must not ask for it.
    canned = CANNED_REPLIES["generating"].lower()
    assert "email" not in canned
    assert "putting" in canned or "together" in canned
