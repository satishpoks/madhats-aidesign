from __future__ import annotations

from app.services import email


def _capture(monkeypatch):
    sent = {}
    def fake_dispatch(to, subject, html, attachments=None):
        sent["html"] = html; sent["attachments"] = attachments or []
        return True
    monkeypatch.setattr(email, "_dispatch", fake_dispatch)
    return sent


def test_preview_email_uses_brand_colour_and_name(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_preview_email(
        to="c@x.example", name="Sam", image_url="http://img", brief="b",
        brand={"primary_colour": "#0055AA"}, store_name="Acme Caps",
    )
    assert "#0055AA" in sent["html"]
    assert "Acme Caps" in sent["html"]


def test_preview_email_inlines_logo_as_cid(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_preview_email(
        to="c@x.example", name="Sam", image_url="http://img",
        brand={"primary_colour": "#0055AA"}, store_name="Acme",
        logo_bytes=b"PNGBYTES",
    )
    cids = [a["content_id"] for a in sent["attachments"]]
    assert any("logo" in c for c in cids)
    assert 'src="cid:' in sent["html"]


def test_preview_email_defaults_without_brand(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_preview_email(to="c@x.example", name="Sam", image_url="http://img")
    assert "#ff5c00" in sent["html"].lower()
    assert "MAD HATS" in sent["html"]
