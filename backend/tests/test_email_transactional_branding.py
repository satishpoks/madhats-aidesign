from __future__ import annotations

from app.services import email


def _capture(monkeypatch):
    sent = {}
    monkeypatch.setattr(email, "_dispatch", lambda to, subject, html, attachments=None: sent.update(html=html, subject=subject) or True)
    return sent


def test_verification_email_branded(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_verification_email("c@x.example", "Sam", "http://verify", store_name="Acme Caps", primary_colour="#0055AA")
    assert "Acme Caps" in sent["html"]
    assert "#0055AA" in sent["html"]
    assert "http://verify" in sent["html"]


def test_verification_email_default(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_verification_email("c@x.example", "Sam", "http://verify")
    assert "http://verify" in sent["html"]
    # Must not crash and must contain the link; default branding tolerated.
