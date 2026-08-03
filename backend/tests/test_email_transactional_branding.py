from __future__ import annotations

from app.services import email


def _capture(monkeypatch):
    sent = {}

    def _fake(to, subject, html, attachments=None):
        sent.update(html=html, subject=subject, attachments=attachments or [])
        return True

    monkeypatch.setattr(email, "_dispatch", _fake)
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


# --- CTA placement -----------------------------------------------------------
# The button used to be appended AFTER the whole body, so it landed under the
# expiry note and the signature, with a blank gap left where the URL had been
# deleted from mid-paragraph. It must stand IN PLACE of the link instead.

def test_verify_button_sits_where_the_link_was_not_after_the_signature(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_verification_email("c@x.example", "Sam", "http://verify")
    html = sent["html"]

    button = html.index("Verify my email")
    assert button < html.index("This link expires")
    assert button < html.index("Ricardo")
    assert html.index("confirm your email") < button


def test_the_expiry_note_and_signature_still_follow_the_button(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_verification_email("c@x.example", "Sam", "http://verify")
    assert "This link expires" in sent["html"]
    assert "Ricardo" in sent["html"]


def test_resume_button_sits_where_its_link_was(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_resume_email("c@x.example", "Sam", "http://resume")
    html = sent["html"]
    assert html.index("Pick up where I left off") < html.index("keep an eye on")


def test_a_body_with_no_link_still_renders_the_button(monkeypatch):
    """Defensive: if the template ever loses its URL placeholder the CTA must
    still be reachable rather than silently vanishing."""
    body = email._body_with_cta("No link in here.", "http://x", "Go", "#123456")
    assert "Go" in body
    assert "http://x" in body


# --- store brand kit ---------------------------------------------------------

def test_header_uses_the_store_header_colours(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_verification_email(
        "c@x.example", "Sam", "http://verify",
        store_name="Acme Caps", primary_colour="#0055AA",
        header_bg="#101820", header_text="#F2AA4C",
    )
    assert "#101820" in sent["html"]
    assert "#F2AA4C" in sent["html"]


def test_header_falls_back_to_the_primary_colour(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_verification_email(
        "c@x.example", "Sam", "http://verify",
        store_name="Acme Caps", primary_colour="#0055AA",
    )
    assert "background:#0055AA" in sent["html"]


def test_the_store_logo_is_inlined_as_an_attachment(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_verification_email(
        "c@x.example", "Sam", "http://verify",
        store_name="Acme Caps", logo_bytes=b"\x89PNG-not-really",
    )
    cids = [a["content_id"] for a in sent["attachments"]]
    assert len(cids) == 1
    assert f'src="cid:{cids[0]}"' in sent["html"]


def test_without_a_logo_the_header_shows_the_store_name(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_verification_email("c@x.example", "Sam", "http://verify",
                                  store_name="Acme Caps")
    assert sent["attachments"] == []
    assert "Acme Caps" in sent["html"]
    assert "cid:" not in sent["html"]


def test_the_quote_reference_email_is_branded_too(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_quote_reference_email(
        "c@x.example", "Sam", "MH-ABC123", store_name="Acme Caps",
        primary_colour="#0055AA", header_bg="#101820",
        logo_bytes=b"\x89PNG-not-really",
    )
    assert "MH-ABC123" in sent["html"]
    assert "#101820" in sent["html"]
    assert len(sent["attachments"]) == 1


def test_html_escaping_survives_a_store_name_with_an_ampersand(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_verification_email("c@x.example", "Sam", "http://verify",
                                  store_name="Smith & Co")
    assert "Smith &amp; Co" in sent["html"]


# --- brand_kit: store row -> the shell's kwargs -------------------------------

def test_brand_kit_reads_the_store_row(monkeypatch):
    monkeypatch.setattr(email.storage, "download_asset", lambda p: b"logo-bytes")
    kit = email.brand_kit({
        "name": "Acme Caps",
        "brand": {"primary_colour": "#0055AA", "header_bg": "#101820",
                  "header_text": "#F2AA4C", "logo_url": "brand/logo.png"},
    })
    assert kit == {"store_name": "Acme Caps", "primary_colour": "#0055AA",
                   "header_bg": "#101820", "header_text": "#F2AA4C",
                   "logo_bytes": b"logo-bytes"}


def test_brand_kit_defaults_for_an_unconfigured_store():
    assert email.brand_kit(None) == {
        "store_name": "MadHats", "primary_colour": "#ff5c00",
        "header_bg": None, "header_text": None, "logo_bytes": None}


def test_brand_kit_survives_a_failed_logo_download(monkeypatch):
    """A branding lookup must never stop a verification email going out."""
    def _boom(_path):
        raise RuntimeError("storage down")

    monkeypatch.setattr(email.storage, "download_asset", _boom)
    kit = email.brand_kit({"name": "Acme", "brand": {"logo_url": "brand/logo.png"}})
    assert kit["logo_bytes"] is None
    assert kit["store_name"] == "Acme"
