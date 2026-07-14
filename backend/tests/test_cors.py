"""CORS config: open (reflect any origin) when ALLOWED_ORIGINS contains '*'.

Browsers reject `Access-Control-Allow-Origin: *` together with
`Access-Control-Allow-Credentials: true`, so for the open case the middleware
reflects the request origin via a catch-all regex instead of a literal "*".

These tests drive `build_cors_kwargs` directly so they don't depend on the
ambient .env (which may pin ALLOWED_ORIGINS to a specific list in dev/prod).
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import build_cors_kwargs


def test_allow_all_origins_flag_default_is_true():
    assert Settings(allowed_origins="*").allow_all_origins is True


def test_allow_all_origins_flag_false_for_explicit_list():
    s = Settings(allowed_origins="https://madhats.com.au,http://localhost:5173")
    assert s.allow_all_origins is False


def test_cors_kwargs_open_uses_reflecting_regex():
    kwargs = build_cors_kwargs(Settings(allowed_origins="*"))
    assert kwargs["allow_origin_regex"] == ".*"
    assert "allow_origins" not in kwargs
    assert kwargs["allow_credentials"] is True


def test_cors_kwargs_locked_uses_explicit_list():
    kwargs = build_cors_kwargs(
        Settings(allowed_origins="https://madhats.com.au,http://localhost:5173")
    )
    assert kwargs["allow_origins"] == [
        "https://madhats.com.au",
        "http://localhost:5173",
    ]
    assert "allow_origin_regex" not in kwargs


def _app_with(cfg: Settings) -> FastAPI:
    app = FastAPI()
    app.add_middleware(CORSMiddleware, **build_cors_kwargs(cfg))

    @app.get("/ping")
    def ping():  # noqa: ANN202
        return {"ok": True}

    return app


def test_open_cors_reflects_arbitrary_origin():
    origin = "https://some-random-shop.myshopify.com"
    client = TestClient(_app_with(Settings(allowed_origins="*")))
    resp = client.get("/ping", headers={"Origin": origin})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_locked_cors_rejects_unlisted_origin():
    app = _app_with(Settings(allowed_origins="https://madhats.com.au"))
    resp = TestClient(app).get("/ping", headers={"Origin": "https://evil.example"})
    # Unlisted origin gets no ACAO header (browser would block it).
    assert resp.headers.get("access-control-allow-origin") is None
