import pytest

from app.services import delivery


class _NoRows:
    """A supabase stub whose every query returns nothing.

    `send_final_design` now opens with the quote gate (C2), which reads the
    session's `collected`. These tests are about the regeneration logic, so the
    session simply isn't found -> not quote-gated -> the original path runs.
    """

    data: list = []

    def table(self, name):
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return self


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(delivery, "get_supabase", lambda: _NoRows())


def test_send_final_design_skips_when_no_regeneration(monkeypatch):
    # Only one generation exists (== the first) -> nothing to resend.
    monkeypatch.setattr(delivery, "_completed_generations", lambda sid: [{"id": "g1", "watermarked_url": "wm1"}])
    assert delivery.send_final_design("s1") is False


def test_send_final_design_sends_when_regenerated(monkeypatch):
    gens = [
        {"id": "g1", "watermarked_url": "wm1", "image_url": "c1"},
        {"id": "g2", "watermarked_url": "wm2", "image_url": "c2"},
    ]
    monkeypatch.setattr(delivery, "_completed_generations", lambda sid: gens)
    monkeypatch.setattr(delivery, "_lead_for_session", lambda sid: {"id": "l1", "email": "a@b.com", "name": "Al", "final_email_sent": False})
    sent = {}
    monkeypatch.setattr(delivery, "_deliver_final", lambda lead, url: sent.setdefault("url", url) or True)
    monkeypatch.setattr(delivery, "_mark_final_sent", lambda lead_id: None)
    assert delivery.send_final_design("s1") is True
    assert sent["url"] == "wm2"
