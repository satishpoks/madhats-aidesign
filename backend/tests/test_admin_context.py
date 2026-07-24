from __future__ import annotations

import pytest

from app.api import deps
from app.config import settings
from app.services import admin_auth


@pytest.mark.asyncio
async def test_env_secret_is_super(monkeypatch):
    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    ctx = await deps.require_admin_ctx(x_admin_secret="envsecret", authorization=None)
    assert ctx.is_super is True
    assert ctx.allowed_store_ids is None


@pytest.mark.asyncio
async def test_bearer_loads_user(monkeypatch):
    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    monkeypatch.setattr(deps.admin_users, "get_by_id", lambda uid: {"id": uid, "email": "a@x.com", "is_super": False, "status": "active"})
    monkeypatch.setattr(deps.admin_users, "allowed_store_ids", lambda uid: {"s1"})
    token = admin_auth.create_token("u1")
    ctx = await deps.require_admin_ctx(x_admin_secret=None, authorization=f"Bearer {token}")
    assert ctx.is_super is False
    assert ctx.allowed_store_ids == {"s1"}


@pytest.mark.asyncio
async def test_disabled_user_rejected(monkeypatch):
    monkeypatch.setattr(deps.admin_users, "get_by_id", lambda uid: {"id": uid, "email": "a@x.com", "is_super": False, "status": "disabled"})
    token = admin_auth.create_token("u1")
    with pytest.raises(deps.HTTPException) as exc:
        await deps.require_admin_ctx(x_admin_secret=None, authorization=f"Bearer {token}")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_no_credentials_rejected(monkeypatch):
    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    with pytest.raises(deps.HTTPException):
        await deps.require_admin_ctx(x_admin_secret=None, authorization=None)


def test_assert_store_allowed():
    superctx = deps.AdminContext(user_id=None, email=None, is_super=True, allowed_store_ids=None)
    deps.assert_store_allowed(superctx, "any")  # no raise
    scoped = deps.AdminContext(user_id="u1", email="a@x.com", is_super=False, allowed_store_ids={"s1"})
    deps.assert_store_allowed(scoped, "s1")  # no raise
    with pytest.raises(deps.HTTPException) as exc:
        deps.assert_store_allowed(scoped, "s2")
    assert exc.value.status_code == 403


def test_require_super():
    scoped = deps.AdminContext(user_id="u1", email="a@x.com", is_super=False, allowed_store_ids={"s1"})
    with pytest.raises(deps.HTTPException) as exc:
        deps.require_super(scoped)
    assert exc.value.status_code == 403
