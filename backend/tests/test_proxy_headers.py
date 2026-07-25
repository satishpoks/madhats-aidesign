"""Behind a reverse proxy, the client IP AND the scheme must come from
X-Forwarded-*.

Two separate consequences ride on this one middleware:

1. slowapi keys rate limits on `request.client.host` (see app/api/deps.py:
   `Limiter(key_func=get_remote_address)`). Once Caddy terminates TLS in front of
   the backend, that field is the PROXY's container IP on every request — which
   silently collapses every customer into a single rate-limit bucket, turning
   RATE_LIMIT_RPM into a site-wide cap.

2. `app/storage.py:media_url` builds every private-asset URL from
   `request.base_url`, whose scheme comes from `scope["scheme"]`. Caddy speaks
   plain HTTP to the backend, so without X-Forwarded-Proto trust every asset URL
   comes back `http://` and is blocked as mixed content on the HTTPS studio.

ProxyHeadersMiddleware rewrites both.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi.util import get_remote_address
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import Settings


def _app(*, trusted: str | list[str] | None) -> FastAPI:
    """Minimal app exposing whatever slowapi would key a rate limit on, plus the
    base URL that `storage.media_url` builds every asset link from."""
    app = FastAPI()

    @app.get("/whoami")
    def whoami(request: Request):  # noqa: ANN202
        return {"ip": get_remote_address(request), "base_url": str(request.base_url)}

    if trusted is not None:
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted)
    return app


def _settings(**overrides: str) -> Settings:
    """Settings built from the CODE defaults, not the ambient environment.

    A bare `Settings()` reads the repo-root `.env` (config.py:14-22) *and* real
    env vars, so it asserts whatever the machine happens to be configured with:
    run inside the backend container — where compose sets TRUSTED_PROXY_HOSTS="*"
    — the default assertion below would fail against correct code. `_env_file=None`
    drops the dotenv sources; the required fields are stubbed so validation still
    passes without them. Init kwargs outrank env vars, so any `overrides` here are
    authoritative. (An OS env var can still win where no override is given — the
    default test additionally clears it.)
    """
    return Settings(
        _env_file=None,
        supabase_url="http://stub.invalid",
        supabase_anon_key="stub",
        supabase_service_role_key="stub",
        admin_secret="stub",
        **overrides,
    )


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


def test_default_trusts_no_proxy(monkeypatch):
    """Fail SAFE. Trusting a forwarded header from an untrusted caller is worse
    than the bug this fixes: anyone reaching the port directly could rotate
    X-Forwarded-For for a fresh rate-limit bucket per request. The deployment
    that closes the port is the deployment that opts in (docker-compose.prod.yml).

    The delenv is not belt-and-braces: `_env_file=None` only drops the dotenv
    sources, so a real TRUSTED_PROXY_HOSTS in the process environment (exactly
    what compose injects into the backend container) would still be read."""
    monkeypatch.delenv("TRUSTED_PROXY_HOSTS", raising=False)
    s = _settings()
    assert s.trusted_proxy_hosts == ""
    assert s.trusted_proxy_hosts_value == []


def test_untrusted_forwarded_header_is_ignored():
    resp = TestClient(_app(trusted=[])).get("/whoami", headers=FORWARDED)
    assert resp.json()["ip"] == "testclient"


def test_wildcard_is_honoured_when_explicitly_configured():
    assert _settings(trusted_proxy_hosts="*").trusted_proxy_hosts_value == "*"


def test_trusted_proxy_hosts_parses_a_comma_list():
    s = _settings(trusted_proxy_hosts="10.0.0.1, 10.0.0.2")
    assert s.trusted_proxy_hosts_value == ["10.0.0.1", "10.0.0.2"]


def test_forwarded_proto_keeps_asset_urls_on_https():
    """app/storage.py:media_url turns every private storage path into an absolute
    ``{request.base_url}media/{token}`` URL — the brand logo, hat-type angles,
    company graphics, blank-hat composites, session view_images, admin thumbnails
    and quote components, ~16 call sites in all.

    Caddy speaks plain HTTP to backend:8000, so `scope["scheme"]` is "http" on the
    wire. Without X-Forwarded-Proto trust every one of those URLs is emitted as
    http:// and the browser blocks it as mixed content on the HTTPS studio: the
    canvas renders with no product photo, no logo, and the admin console shows no
    thumbnails. That is the loud symptom of this middleware being missing; the
    rate-limit bucket collapse is the quiet one."""
    resp = TestClient(_app(trusted="*")).get("/whoami", headers=FORWARDED)
    assert resp.json()["base_url"] == "https://testserver/"


def test_without_the_middleware_asset_urls_stay_on_http():
    """The failure mode the test above protects against."""
    resp = TestClient(_app(trusted=None)).get("/whoami", headers=FORWARDED)
    assert resp.json()["base_url"] == "http://testserver/"


def test_proxy_headers_is_the_outermost_middleware():
    """Starlette's add_middleware inserts at index 0, so the LAST-added runs
    FIRST. ProxyHeadersMiddleware must be outermost, otherwise SlowAPIMiddleware
    reads request.client.host before it has been rewritten."""
    from app.main import app

    assert app.user_middleware[0].cls is ProxyHeadersMiddleware


def test_the_configured_trust_is_what_reaches_the_middleware():
    """Without this, hardcoding trusted_hosts="*" in main.py would pass every
    other test in this file — the setting would be decorative, and the fail-safe
    default above would be a lie."""
    from app.config import settings
    from app.main import app

    assert app.user_middleware[0].kwargs["trusted_hosts"] == (
        settings.trusted_proxy_hosts_value
    )
