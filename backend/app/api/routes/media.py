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

# This proxy is a token-authorised, credential-free PUBLIC endpoint: it serves
# <img> tags in customer emails and the studio widget embedded on arbitrary
# Shopify store origins, and is fetch()'d for download from the admin panel on a
# different port than the backend. Those origins are not in the global CORS
# allow-list, so the endpoint emits its own Access-Control-Allow-Origin instead
# of relying on CORSMiddleware. "*" is safe here — the URL capability token is
# the sole authorisation and no cookies/credentials are involved. When the global
# middleware DOES cover the origin it overwrites this single header (no duplicate).
_CORS = {"Access-Control-Allow-Origin": "*"}


@router.get("/media/{token}")
async def media(token: str) -> Response:
    try:
        path = decode_media_token(token)
    except MediaTokenError:
        return Response(status_code=404, headers=_CORS)

    # Sign for the backend's own fetch (internal host is backend-reachable), then
    # stream the bytes. Reuses the same fetch helper as the email/quote proxies.
    data = _fetch_image_bytes(generate_signed_url(path))
    if data is None:
        log.warning("media_fetch_failed")  # path not logged (may reveal object layout)
        return Response(status_code=502, headers=_CORS)

    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300", **_CORS},
    )
