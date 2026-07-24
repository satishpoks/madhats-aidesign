from __future__ import annotations

from app.services import admin_auth


def test_hash_then_verify_roundtrip():
    stored = admin_auth.hash_password("hunter2")
    assert stored.startswith("pbkdf2_sha256$600000$")
    assert admin_auth.verify_password("hunter2", stored) is True
    assert admin_auth.verify_password("wrong", stored) is False


def test_hash_is_salted_unique():
    assert admin_auth.hash_password("x") != admin_auth.hash_password("x")


def test_verify_rejects_malformed_record():
    assert admin_auth.verify_password("x", "not-a-real-record") is False
    assert admin_auth.verify_password("x", "") is False


def test_token_roundtrip():
    token = admin_auth.create_token("user-123")
    assert admin_auth.decode_token(token) == "user-123"


def test_decode_rejects_garbage_and_tampered():
    assert admin_auth.decode_token("garbage.token.here") is None
    good = admin_auth.create_token("u1")
    assert admin_auth.decode_token(good + "x") is None
