"""Quote link token — signed with ADMIN_SECRET, purpose-scoped, expiring."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from app.services import leads as leads_service


def test_round_trip():
    token = leads_service.make_quote_token({"id": "lead-1", "session_id": "sess-1"})
    payload = leads_service.decode_quote_token(token)
    assert payload["lead_id"] == "lead-1"
    assert payload["session_id"] == "sess-1"
    assert payload["purpose"] == "quote"


def test_expired_token_rejected():
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    token = jwt.encode(
        {"lead_id": "lead-1", "session_id": "sess-1", "purpose": "quote", "exp": past},
        settings.admin_secret,
        algorithm="HS256",
    )
    with pytest.raises(leads_service.QuoteTokenError):
        leads_service.decode_quote_token(token)


def test_wrong_purpose_rejected():
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    token = jwt.encode(
        {"lead_id": "lead-1", "session_id": "sess-1", "purpose": "verify", "exp": future},
        settings.admin_secret,
        algorithm="HS256",
    )
    with pytest.raises(leads_service.QuoteTokenError):
        leads_service.decode_quote_token(token)


def test_tampered_token_rejected():
    with pytest.raises(leads_service.QuoteTokenError):
        leads_service.decode_quote_token("not-a-real-jwt")
