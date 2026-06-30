"""Supabase client singleton.

Uses the service-role key — RLS is bypassed by the backend. Customer-facing
access control is enforced in the API layer, never by exposing this client.
"""
from __future__ import annotations

from supabase import Client, create_client

from app.config import settings

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _client
