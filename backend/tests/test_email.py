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
