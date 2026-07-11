"""Media proxy — stream a private storage object to a client browser.

Opened via /media/{token}, where the token is a signed capability naming ONE
storage object (app.storage.make_media_token). This lets the admin panel (and
any client) render private bucket images without ever exposing the storage host
or the bucket itself: the backend fetches the bytes server-side and streams them
back from its own origin. An <img> tag can't send the X-Admin-Secret header, so
the URL-embedded capability token is the authorisation.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter
from fastapi.responses import Response

from app.services.delivery import _fetch_image_bytes
from app.storage import MediaTokenError, decode_media_token, generate_signed_url

router = APIRouter(tags=["media"])
log = structlog.get_logger()


@router.get("/media/{token}")
async def media(token: str) -> Response:
    try:
        path = decode_media_token(token)
    except MediaTokenError:
        return Response(status_code=404)

    # Sign for the backend's own fetch (internal host is backend-reachable), then
    # stream the bytes. Reuses the same fetch helper as the email/quote proxies.
    data = _fetch_image_bytes(generate_signed_url(path))
    if data is None:
        log.warning("media_fetch_failed")  # path not logged (may reveal object layout)
        return Response(status_code=502)

    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )
