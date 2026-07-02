"""Asserts the quote link TTL defaults to 30 days (2592000 seconds) when no
env override is set."""
from __future__ import annotations


def test_quote_token_ttl_default():
    from app.config import settings

    # 30 days in seconds. Longer than the 15-min verify link because a quote
    # offer stays valid a while and the customer may click days later.
    assert settings.quote_token_ttl_seconds == 2592000
