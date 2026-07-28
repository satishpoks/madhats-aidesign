"""GET /leads/verify/{token} — the landing page follows the store's brand.

The last customer-facing surface the per-store branding work missed: it
hardcoded #ff5c00 and the MadHats lockup, so a branded store's customer clicked
a themed email and landed on an orange MadHats page.

Branding here is strictly cosmetic and strictly best-effort: the verification is
already committed to the database before the page renders, so a store lookup
that fails must still return 200.
"""
from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.routes import leads as leads_route
from app.config import settings
from app.main import app


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, *a, **k):
        return self

    def execute(self):
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, session_row):
        self._session_row = session_row

    def table(self, name):
        if name == "email_verifications":
            return _Query([{"id": "ver-1"}])
        if name == "leads":
            return _Query([{"id": "lead-1", "session_id": "sess-1",
                            "email": "c@x.example", "name": "Sam"}])
        if name == "design_sessions":
            return _Query([self._session_row])
        raise AssertionError(f"unexpected table {name}")


client = TestClient(app)


def _token():
    return jwt.encode({"lead_id": "lead-1"}, settings.admin_secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def _quiet_side_effects(monkeypatch):
    """The route's post-verification email sends are irrelevant here and must not
    hit the network. Each is already best-effort in the route."""
    monkeypatch.setattr(leads_route.delivery, "maybe_send_preview", lambda sid: False)
    monkeypatch.setattr(leads_route.delivery, "maybe_send_quote_confirmation", lambda sid: None)
    monkeypatch.setattr(leads_route, "_maybe_send_resume_email", lambda *a, **k: None)
    monkeypatch.setattr(leads_route, "_mark_session_verified", lambda *a, **k: None)


def _setup(monkeypatch, session_row, store):
    monkeypatch.setattr(leads_route, "get_supabase", lambda: _FakeSB(session_row))
    monkeypatch.setattr("app.services.stores.get_store", lambda sid: store)


def test_a_branded_store_themes_the_success_page(monkeypatch):
    _setup(monkeypatch, {"store_id": "store-1"},
           {"id": "store-1", "name": "Acme Caps",
            "brand": {"primary_colour": "#123456"}})

    resp = client.get(f"/leads/verify/{_token()}")

    assert resp.status_code == 200
    assert "#123456" in resp.text
    assert "Acme Caps" in resp.text
    assert "#ff5c00" not in resp.text
    assert "MAD HATS" not in resp.text


def test_an_unconfigured_store_keeps_the_madhats_defaults(monkeypatch):
    _setup(monkeypatch, {"store_id": None}, None)

    resp = client.get(f"/leads/verify/{_token()}")

    assert resp.status_code == 200
    assert "#ff5c00" in resp.text
    assert "MAD HATS" in resp.text
    assert "AI Design Studio" in resp.text


def test_a_store_lookup_that_raises_still_verifies(monkeypatch):
    """The verification is already committed. Branding must never downgrade a
    success into an error page."""
    def _boom(_sid):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(leads_route, "get_supabase", lambda: _FakeSB({"store_id": "store-1"}))
    monkeypatch.setattr("app.services.stores.get_store", _boom)

    resp = client.get(f"/leads/verify/{_token()}")

    assert resp.status_code == 200
    assert "Your email is now verified" in resp.text
    assert "#ff5c00" in resp.text


def test_the_close_message_is_highlighted_on_the_success_page(monkeypatch):
    _setup(monkeypatch, {"store_id": None}, None)

    resp = client.get(f"/leads/verify/{_token()}")

    assert "You can close this page now and head back to the chat." in resp.text
    assert "border-left:4px solid" in resp.text     # the callout treatment


def test_the_callout_border_follows_the_store_colour(monkeypatch):
    _setup(monkeypatch, {"store_id": "store-1"},
           {"id": "store-1", "name": "Acme Caps",
            "brand": {"primary_colour": "#123456"}})

    resp = client.get(f"/leads/verify/{_token()}")

    assert "border-left:4px solid #123456" in resp.text


def test_a_configured_logo_is_rendered_as_a_media_url(monkeypatch):
    _setup(monkeypatch, {"store_id": "store-1"},
           {"id": "store-1", "name": "Acme Caps",
            "brand": {"primary_colour": "#123456", "logo_url": "brands/acme.png"}})

    resp = client.get(f"/leads/verify/{_token()}")

    assert "<img" in resp.text
    assert "/media/" in resp.text


def test_an_expired_link_renders_the_default_themed_error_page():
    """No lead is loaded for an expired token, so there is no store to resolve.
    Documented in the spec as accepted."""
    expired = jwt.encode(
        {"lead_id": "lead-1", "exp": 0}, settings.admin_secret, algorithm="HS256")

    resp = client.get(f"/leads/verify/{expired}")

    assert resp.status_code == 400
    assert "This link has expired" in resp.text
    assert "MAD HATS" in resp.text


def test_a_malformed_link_renders_the_error_page():
    resp = client.get("/leads/verify/not-a-real-token")

    assert resp.status_code == 400
    assert "doesn&#x27;t look right" in resp.text or "doesn't look right" in resp.text
