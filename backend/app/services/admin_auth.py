"""Admin-user auth primitives: PBKDF2 password hashing + HS256 JWT sessions.

Pure functions, no DB. Password records are stdlib PBKDF2-HMAC-SHA256 (no
native dependency). Tokens carry only the user id (`sub`); status and assigned
stores are re-loaded per request (see api/deps.py) for immediate revocation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 600_000
_JWT_ALG = "HS256"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_b64, hash_b64 = stored.split("$")
        if algo != _ALGO:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iters_s)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def create_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.admin_jwt_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.admin_jwt_signing_key, algorithm=_JWT_ALG)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.admin_jwt_signing_key, algorithms=[_JWT_ALG])
    except jwt.InvalidTokenError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None
