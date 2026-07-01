"""maybe_send_preview() — the single gated delivery primitive.

Preview + sales emails must only go out when BOTH the email is verified AND
a completed generation with a real image exists. This closes the race where
the customer verifies before generation finishes (or generation fails),
which used to send a blank-image email at verification time.
"""
from __future__ import annotations

import jwt

from app.config import settings
from app.services import delivery


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Minimal chainable stand-in for a supabase-py table query.

    Filters (`eq`/`is_`/`order`/`limit`) narrow `self._rows` immediately.
    `update`/`insert` are deferred until `execute()` so they apply
    regardless of call order (`.update(...).eq(...)` or `.eq(...).update(...)`)
    and mutate the underlying row dicts in place, so later queries in the
    same test (or a second call to the function under test) see the change.
    """

    def __init__(self, table, rows, sink):
        self._table = table
        self._rows = rows
        self._sink = sink
        self._pending_update = None
        self._pending_insert = None

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def is_(self, field, value):
        if value == "null":
            self._rows = [r for r in self._rows if r.get(field) is None]
        return self

    def order(self, field, desc=False, **k):
        self._rows = sorted(self._rows, key=lambda r: r.get(field) or "", reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def insert(self, payload):
        self._pending_insert = payload
        return self

    def execute(self):
        if self._pending_update is not None:
            self._sink.setdefault(self._table, {}).setdefault("updates", []).append(
                self._pending_update
            )
            for row in self._rows:
                row.update(self._pending_update)
        if self._pending_insert is not None:
            self._sink.setdefault(self._table, {}).setdefault("inserts", []).append(
                self._pending_insert
            )
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, tables: dict):
        self._tables = tables
        self.sink: dict = {}

    def table(self, name):
        rows = list(self._tables.get(name, []))
        return _Query(name, rows, self.sink)


def _session_row(**overrides):
    row = {
        "id": "sess-1",
        "collected": {"decoration_type": "embroidery", "placement_zone": "front_panel", "quantity": 24},
        "product_ref": {"product_id": "prod-1"},
        "store_id": None,
        "share_token": "share-tok",
    }
    row.update(overrides)
    return row


def _lead_row(**overrides):
    row = {
        "id": "lead-1",
        "session_id": "sess-1",
        "name": "Ann",
        "email": "ann@example.com",
        "phone": None,
        "email_verified": True,
        "preview_email_sent": False,
        "quote_request_sent": False,
        "created_at": "2026-07-01T00:00:00Z",
    }
    row.update(overrides)
    return row


def _generation_row(**overrides):
    row = {
        "id": "gen-1",
        "session_id": "sess-1",
        "status": "complete",
        "watermarked_url": "generations/wm.png",
        "image_url": "generations/clean.png",
        "created_at": "2026-07-01T00:01:00Z",
    }
    row.update(overrides)
    return row


def _patch_common(monkeypatch, fake, sent):
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)
    monkeypatch.setattr(delivery, "get_product", lambda *a, **k: {"name": "Snapback"})
    monkeypatch.setattr(delivery, "generate_signed_url", lambda path: f"signed:{path}")

    def _fake_preview(*args, **kwargs):
        sent.setdefault("preview", []).append((args, kwargs))
        return True

    def _fake_quote(*args, **kwargs):
        sent.setdefault("quote", []).append((args, kwargs))
        return True

    monkeypatch.setattr(delivery.email_service, "send_preview_email", _fake_preview)
    monkeypatch.setattr(delivery.email_service, "send_quote_to_sales", _fake_quote)

    import app.services.stores as stores_mod

    monkeypatch.setattr(stores_mod, "get_store", lambda _sid: None)


def test_sends_once_then_idempotent(monkeypatch):
    lead = _lead_row()
    tables = {
        "leads": [lead],
        "generations": [_generation_row()],
        "design_sessions": [_session_row()],
    }
    fake = _FakeSB(tables)
    sent: dict = {}
    _patch_common(monkeypatch, fake, sent)

    result = delivery.maybe_send_preview("sess-1")

    assert result is True
    assert len(sent.get("preview", [])) == 1
    assert len(sent.get("quote", [])) == 1
    assert lead["preview_email_sent"] is True
    assert lead["quote_request_sent"] is True

    # Second call: gate 3 (already sent) must block a resend.
    result2 = delivery.maybe_send_preview("sess-1")

    assert result2 is False
    assert len(sent.get("preview", [])) == 1
    assert len(sent.get("quote", [])) == 1


def test_gate_unverified_email_blocks_send(monkeypatch):
    lead = _lead_row(email_verified=False)
    tables = {
        "leads": [lead],
        "generations": [_generation_row()],
        "design_sessions": [_session_row()],
    }
    fake = _FakeSB(tables)
    sent: dict = {}
    _patch_common(monkeypatch, fake, sent)

    result = delivery.maybe_send_preview("sess-1")

    assert result is False
    assert sent.get("preview") is None
    assert lead["preview_email_sent"] is False


def test_gate_no_complete_generation_blocks_send(monkeypatch):
    lead = _lead_row()
    tables = {
        "leads": [lead],
        "generations": [],  # generation still pending / never created
        "design_sessions": [_session_row()],
    }
    fake = _FakeSB(tables)
    sent: dict = {}
    _patch_common(monkeypatch, fake, sent)

    result = delivery.maybe_send_preview("sess-1")

    assert result is False
    assert sent.get("preview") is None


def test_gate_complete_generation_without_image_blocks_send(monkeypatch):
    """The blank-email bug: a 'complete' row with no image must never send."""
    lead = _lead_row()
    tables = {
        "leads": [lead],
        "generations": [_generation_row(watermarked_url=None, image_url=None)],
        "design_sessions": [_session_row()],
    }
    fake = _FakeSB(tables)
    sent: dict = {}
    _patch_common(monkeypatch, fake, sent)

    result = delivery.maybe_send_preview("sess-1")

    assert result is False
    assert sent.get("preview") is None


def test_mixed_state_sales_already_sent_preview_not_yet(monkeypatch):
    """quote_request_sent=True (sales already notified earlier) but
    preview_email_sent=False (customer preview never went out, e.g. it failed
    generation the first time and was manually regenerated). The preview email
    must still fire; the sales email must NOT re-fire."""
    lead = _lead_row(quote_request_sent=True, preview_email_sent=False)
    tables = {
        "leads": [lead],
        "generations": [_generation_row()],
        "design_sessions": [_session_row()],
    }
    fake = _FakeSB(tables)
    sent: dict = {}
    _patch_common(monkeypatch, fake, sent)

    result = delivery.maybe_send_preview("sess-1")

    assert result is True
    assert len(sent.get("preview", [])) == 1
    assert sent.get("quote") is None
    assert lead["preview_email_sent"] is True
    assert lead["quote_request_sent"] is True


def test_verify_route_triggers_send(monkeypatch):
    """Hitting the verify link for a lead whose generation is already complete
    results in the preview being sent from confirm_verification."""
    from app.api.routes import leads as leads_routes

    token = jwt.encode({"lead_id": "lead-1"}, settings.admin_secret, algorithm="HS256")
    token_hash = leads_routes.leads_service.hash_token(token)

    lead = _lead_row(email_verified=False, preview_email_sent=False)
    verification = {"id": "ver-1", "token_hash": token_hash, "used_at": None}
    tables = {
        "leads": [lead],
        "email_verifications": [verification],
        "generations": [_generation_row()],
        "design_sessions": [_session_row()],
    }
    fake = _FakeSB(tables)
    sent: dict = {}

    monkeypatch.setattr(leads_routes, "get_supabase", lambda: fake)
    _patch_common(monkeypatch, fake, sent)

    import asyncio

    html = asyncio.run(leads_routes.confirm_verification(token))

    assert html.status_code == 200
    assert lead["email_verified"] is True
    assert lead["preview_email_sent"] is True
    assert len(sent.get("preview", [])) == 1
