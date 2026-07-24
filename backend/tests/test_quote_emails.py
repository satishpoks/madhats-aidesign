"""Customer reference email (no image) + sales quote-request email (C2/C3)."""
from __future__ import annotations

from app.services import email as email_service


def test_reference_email_carries_code_and_no_image(monkeypatch):
    captured = {}

    def _dispatch(to, subject, html, attachments=None):
        captured.update(to=to, subject=subject, html=html, attachments=attachments)
        return True

    monkeypatch.setattr(email_service, "_dispatch", _dispatch)

    ok = email_service.send_quote_reference_email(
        "ann@example.com", "Ann", "MH-BCDFGH",
        store_name="MadHats", primary_colour="#ff5c00",
    )
    assert ok is True
    assert "MH-BCDFGH" in captured["html"]
    assert captured["attachments"] is None        # no design image to the customer
    assert "Ann" in captured["html"]


def test_sales_request_email_attaches_components(monkeypatch):
    captured = {}

    def _send(to, subject, html, attachments=None):
        captured.update(to=to, subject=subject, html=html, attachments=attachments)
        return True

    monkeypatch.setattr(email_service, "_dispatch", _send)

    attachments = [{"filename": "c0.png", "content": "AAAA",
                    "content_type": "image/png"}]
    ok = email_service.send_quote_request_to_sales(
        "sales@store.com", "MH-BCDFGH", "MadHats", "ann@example.com",
        {"quantity": 24, "needed_by": "2-4 weeks", "purpose": "team",
         "decoration_type": "embroidery",
         "brief_notes": ["Decoration method: embroidery"]},
        attachments,
    )
    assert ok is True
    assert captured["to"] == "sales@store.com"
    assert "MH-BCDFGH" in captured["html"]
    assert "24" in captured["html"] and "2-4 weeks" in captured["html"]
    assert captured["attachments"] == attachments


def test_sales_request_email_no_recipient_returns_false(monkeypatch):
    monkeypatch.setattr(email_service, "_dispatch", lambda *a, **k: True)
    assert email_service.send_quote_request_to_sales(
        None, "MH-X", "MadHats", "a@b.com", {}, []) is False
