"""Behind a reverse proxy, the client IP must come from X-Forwarded-For.

slowapi keys rate limits on `request.client.host` (see app/api/deps.py:
`Limiter(key_func=get_remote_address)`). Once Caddy terminates TLS in front of
the backend, that field is the PROXY's container IP on every request — which
silently collapses every customer into a single rate-limit bucket, turning
RATE_LIMIT_RPM into a site-wide cap. ProxyHeadersMiddleware rewrites it.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi.util import get_remote_address
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import Settings


def _app(*, trusted: str | list[str] | None) -> FastAPI:
    """Minimal app exposing whatever slowapi would key a rate limit on."""
    app = FastAPI()

    @app.get("/whoami")
    def whoami(request: Request):  # noqa: ANN202
        return {"ip": get_remote_address(request)}

    if trusted is not None:
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted)
    return app


FORWARDED = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"}


def test_without_the_middleware_the_forwarded_ip_is_ignored():
    """Documents the bug this middleware exists to prevent."""
    resp = TestClient(_app(trusted=None)).get("/whoami", headers=FORWARDED)
    assert resp.json()["ip"] == "testclient"


def test_forwarded_for_becomes_the_rate_limit_key():
    resp = TestClient(_app(trusted="*")).get("/whoami", headers=FORWARDED)
    assert resp.json()["ip"] == "203.0.113.9"


def test_direct_request_without_forwarded_header_is_unaffected():
    resp = TestClient(_app(trusted="*")).get("/whoami")
    assert resp.json()["ip"] == "testclient"


def test_two_clients_behind_the_proxy_get_distinct_keys():
    """The actual regression: distinct customers must not share a bucket."""
    client = TestClient(_app(trusted="*"))
    a = client.get("/whoami", headers={"X-Forwarded-For": "198.51.100.1"}).json()
    b = client.get("/whoami", headers={"X-Forwarded-For": "198.51.100.2"}).json()
    assert a["ip"] != b["ip"]


def test_trusted_proxy_hosts_defaults_to_wildcard():
    assert Settings(trusted_proxy_hosts="*").trusted_proxy_hosts_value == "*"


def test_trusted_proxy_hosts_parses_a_comma_list():
    s = Settings(trusted_proxy_hosts="10.0.0.1, 10.0.0.2")
    assert s.trusted_proxy_hosts_value == ["10.0.0.1", "10.0.0.2"]


def test_proxy_headers_is_the_outermost_middleware():
    """Starlette's add_middleware inserts at index 0, so the LAST-added runs
    FIRST. ProxyHeadersMiddleware must be outermost, otherwise SlowAPIMiddleware
    reads request.client.host before it has been rewritten."""
    from app.main import app

    assert app.user_middleware[0].cls is ProxyHeadersMiddleware
