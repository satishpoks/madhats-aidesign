"""Media proxy — /media/{token} streams private storage objects to browsers,
and media_url() builds the capability-token URLs that point at it."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import storage


def test_media_url_passes_external_urls_through():
    url = "https://cdn.shopify.com/x/cap.png"
    assert storage.media_url(url, "http://host:8000/") == url


def test_media_url_none_for_empty():
    assert storage.media_url(None, "http://host:8000/") is None
    assert storage.media_url("", "http://host:8000/") is None


def test_media_url_tokenises_storage_path():
    url = storage.media_url("generated/final/x.png", "http://100.103.149.17:8000/")

    assert url is not None
    assert url.startswith("http://100.103.149.17:8000/media/")
    token = url.rsplit("/", 1)[-1]
    # Round-trips back to the exact path — the token IS the capability.
    assert storage.decode_media_token(token) == "generated/final/x.png"


def test_make_decode_round_trip():
    token = storage.make_media_token("watermarked/y.png")
    assert storage.decode_media_token(token) == "watermarked/y.png"


def test_decode_rejects_garbage():
    with pytest.raises(storage.MediaTokenError):
        storage.decode_media_token("not-a-jwt")


def test_decode_rejects_wrong_purpose():
    import jwt

    from app.config import settings

    bad = jwt.encode({"path": "x.png", "purpose": "quote"}, settings.admin_secret, algorithm="HS256")
    with pytest.raises(storage.MediaTokenError):
        storage.decode_media_token(bad)


@pytest.fixture()
def client():
    from app.main import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_proxy_streams_bytes(client, monkeypatch):
    from app.api.routes import media

    captured = {}

    def _fake_signed(path):
        captured["path"] = path
        return f"http://host.docker.internal:54321/signed/{path}"

    monkeypatch.setattr(media, "generate_signed_url", _fake_signed)
    monkeypatch.setattr(media, "_fetch_image_bytes", lambda url: b"\x89PNG-media")

    token = storage.make_media_token("generated/final/x.png")
    resp = client.get(f"/media/{token}")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")
    assert resp.content == b"\x89PNG-media"
    # It signed and fetched the exact path the token authorised.
    assert captured["path"] == "generated/final/x.png"


def test_proxy_bad_token_404(client):
    resp = client.get("/media/not-a-real-token")
    assert resp.status_code == 404


def test_proxy_fetch_failure_502(client, monkeypatch):
    from app.api.routes import media

    monkeypatch.setattr(media, "generate_signed_url", lambda p: "http://x/y")
    monkeypatch.setattr(media, "_fetch_image_bytes", lambda url: None)

    token = storage.make_media_token("generated/final/x.png")
    resp = client.get(f"/media/{token}")

    assert resp.status_code == 502


# --- CORS: the proxy is a token-authorised, credential-free PUBLIC endpoint ---
# It serves <img> tags in emails and the widget embedded on arbitrary Shopify
# store origins, and is fetched for download from the admin panel on a DIFFERENT
# port than the backend. It must therefore emit its own Access-Control-Allow-Origin,
# not rely on the global CORS allow-list (which omits those origins). Display works
# cross-origin without CORS, but fetch()-based download does not.


def _media_app(cfg):
    """A minimal app mirroring main.py's CORS wiring + the media router."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from app.api.routes import media
    from app.main import build_cors_kwargs

    app = FastAPI()
    app.add_middleware(CORSMiddleware, **build_cors_kwargs(cfg))
    app.include_router(media.router)
    return app


def _stub_fetch(monkeypatch):
    from app.api.routes import media

    monkeypatch.setattr(media, "generate_signed_url", lambda p: "http://x/y")
    monkeypatch.setattr(media, "_fetch_image_bytes", lambda url: b"\x89PNG")


def test_proxy_sets_acao_for_origin_not_in_allowlist(monkeypatch):
    """A locked ALLOWED_ORIGINS list omits the Shopify widget / admin-port origin;
    the proxy still returns ACAO:* so the browser allows the download fetch."""
    from app.config import Settings

    _stub_fetch(monkeypatch)
    app = _media_app(Settings(allowed_origins="https://madhats.com.au"))
    token = storage.make_media_token("generated/final/x.png")

    resp = TestClient(app).get(
        f"/media/{token}", headers={"Origin": "https://some-shop.myshopify.com"}
    )

    assert resp.status_code == 200
    assert resp.headers.get_list("access-control-allow-origin") == ["*"]


def test_proxy_acao_not_duplicated_when_global_cors_also_sets_it(monkeypatch):
    """With the default open CORS the global middleware also emits ACAO; the
    proxy's own header must not produce a second (browsers reject two ACAOs)."""
    from app.config import Settings

    _stub_fetch(monkeypatch)
    app = _media_app(Settings(allowed_origins="*"))
    token = storage.make_media_token("generated/final/x.png")

    resp = TestClient(app).get(
        f"/media/{token}", headers={"Origin": "https://some-shop.myshopify.com"}
    )

    assert resp.status_code == 200
    assert len(resp.headers.get_list("access-control-allow-origin")) == 1
