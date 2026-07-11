"""Email sending is best-effort — a provider error must never propagate.

A Resend failure (test-mode recipient limits, quota, network) used to crash the
caller; e.g. the /leads/verify endpoint 500'd when the internal sales
notification was rejected, even though verification had already succeeded.
"""
from __future__ import annotations

import types

from app.services import email as email_service


def test_send_swallows_provider_error(monkeypatch):
    monkeypatch.setattr(email_service.settings, "resend_api_key", "test-key")

    class _ResendError(Exception):
        # Mimics resend.ResendError carrying a message that echoes a recipient.
        code = "403"
        error_type = "validation_error"

    class _FakeEmails:
        @staticmethod
        def send(_params):
            raise _ResendError("You can only send to owner (someone@example.com)")

    monkeypatch.setattr(
        email_service, "resend", types.SimpleNamespace(api_key=None, Emails=_FakeEmails)
    )

    # Must return False, not raise.
    assert email_service._send("dest@example.com", "Subject", "Body") is False


def test_send_skips_when_no_provider(monkeypatch):
    monkeypatch.setattr(email_service.settings, "resend_api_key", "")
    assert email_service._send("dest@example.com", "Subject", "Body") is False


def _capture_send(monkeypatch):
    """Patch Resend to capture the exact payload passed to Emails.send."""
    monkeypatch.setattr(email_service.settings, "resend_api_key", "test-key")
    captured: dict = {}

    class _FakeEmails:
        @staticmethod
        def send(params):
            captured["params"] = params

    monkeypatch.setattr(
        email_service, "resend", types.SimpleNamespace(api_key=None, Emails=_FakeEmails)
    )
    return captured


def test_preview_email_inlines_image_bytes_as_cid_attachment(monkeypatch):
    """When raw image bytes are supplied the image must ride along as an inline
    CID attachment (works on localhost + in prod, never expires, no external
    fetch by the recipient's mail client) — never a bare <img src=http…> URL
    the recipient can't reach."""
    import base64

    captured = _capture_send(monkeypatch)
    png = b"\x89PNG\r\n\x1a\n-fake-bytes"

    ok = email_service.send_preview_email(
        "dest@example.com", "Sam", "http://127.0.0.1:54321/whatever", image_bytes=png
    )

    assert ok is True
    params = captured["params"]
    attachments = params.get("attachments")
    assert attachments and len(attachments) == 1
    att = attachments[0]
    cid = att["content_id"]
    # HTML references the attachment by cid: and NOT by the unreachable URL.
    assert f"cid:{cid}" in params["html"]
    assert "127.0.0.1" not in params["html"]
    # Attachment carries the actual bytes, base64-encoded.
    assert base64.b64decode(att["content"]) == png


def test_preview_email_without_bytes_falls_back_to_url_src(monkeypatch):
    """Backward-compatible / best-effort fallback: if we couldn't fetch the
    bytes, still send with the URL src rather than a blank image."""
    captured = _capture_send(monkeypatch)

    ok = email_service.send_preview_email(
        "dest@example.com", "Sam", "https://cdn.example.com/x.png"
    )

    assert ok is True
    params = captured["params"]
    assert not params.get("attachments")
    assert "https://cdn.example.com/x.png" in params["html"]


def test_quote_confirmation_to_sales_includes_confirmed_details(monkeypatch):
    """The 'customer confirmed' sales email must carry the confirmed quantity,
    phone, phone-notify consent, and any customer note so the rep can follow up."""
    captured = _capture_send(monkeypatch)

    ok = email_service.send_quote_confirmation_to_sales(
        customer={"name": "Ann", "email": "ann@example.com", "phone": "0400000000"},
        product={"name": "Snapback", "style": "6-panel", "colour": "black"},
        collected={
            "quantity": 50,
            "decoration_type": "embroidery",
            "placement_zone": "front_panel",
            "placement_position": "centre",
        },
        note="Need them before the expo",
        notify_by_phone=True,
        image_url="https://cdn/clean.png",
        recipient="sales@store.example",
    )

    assert ok is True
    params = captured["params"]
    assert params["to"] == ["sales@store.example"]
    assert "50" in params["subject"]
    body = params["html"]
    assert "0400000000" in body
    assert "Need them before the expo" in body
    # phone-notify consent surfaced for the rep
    assert "yes" in body.lower()


def test_quote_to_sales_includes_per_element_design_brief(monkeypatch):
    """Finding 2 (whole-branch review): the sales team must see the per-element
    design details, not just the retired flat placement fields (which are
    empty/stale once the conversation moved to collected["elements"])."""
    captured = _capture_send(monkeypatch)

    ok = email_service.send_quote_to_sales(
        customer={"name": "Ann", "email": "ann@example.com", "phone": None},
        product={"name": "Snapback", "style": "6-panel", "colour": "black"},
        collected={
            "quantity": 50,
            "decoration_type": "embroidery",
            "elements": [
                {
                    "type": "text", "content": "TEAM SPIRIT", "style": "bold", "colour": "gold",
                    "placement_zone": "front_panel", "placement_position": "centre",
                },
            ],
        },
        image_url="https://cdn/clean.png",
        recipient="sales@store.example",
    )

    assert ok is True
    body = captured["params"]["html"]
    assert 'Text "TEAM SPIRIT" — bold, gold, on the front panel (centre)' in body


def test_quote_confirmation_to_sales_includes_per_element_design_brief(monkeypatch):
    """Same brief requirement for the 'customer confirmed' sales email."""
    captured = _capture_send(monkeypatch)

    ok = email_service.send_quote_confirmation_to_sales(
        customer={"name": "Ann", "email": "ann@example.com", "phone": "0400000000"},
        product={"name": "Snapback", "style": "6-panel", "colour": "black"},
        collected={
            "quantity": 50,
            "decoration_type": "embroidery",
            "elements": [
                {"type": "graphic", "content": "a star", "style": "minimalist", "colour": "navy",
                 "placement_zone": "side"},
            ],
        },
        note="",
        notify_by_phone=False,
        image_url="https://cdn/clean.png",
        recipient="sales@store.example",
    )

    assert ok is True
    body = captured["params"]["html"]
    assert "Graphic: a star — minimalist, navy, on the side" in body
