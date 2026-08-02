"""Admin store (tenant) management. All routes gated by X-Admin-Secret.

Onboarding a new store: POST /admin/stores -> (auto public_key) -> then
POST /admin/stores/{id}/sync to pull its Shopify catalogue.
"""
from __future__ import annotations

import json
import re
import secrets

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse

from app.api.deps import AdminContext, assert_store_allowed, require_admin_ctx, require_super
from app.db import get_supabase
from app.models.store import CreateStoreRequest, StoreResponse, SyncResponse, UpdateStoreRequest
from app.services.branding import validate_brand
from app.services import catalogue_ingest
from app.services.catalogue_sync import seconds_until_next_sync
from app.services.upload_validation import MAX_UPLOAD_BYTES, sniff_image_mime
from app.storage import media_url, upload_asset

router = APIRouter(tags=["admin-stores"])
log = structlog.get_logger()


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _load_store(store_id: str) -> dict:
    res = get_supabase().table("stores").select("*").eq("id", store_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    return res.data[0]


def _gen_public_key(slug: str) -> str:
    return f"mh_pk_{slug}_{secrets.token_hex(6)}"


@router.post("/admin/stores", response_model=StoreResponse)
async def create_store(body: CreateStoreRequest, ctx: AdminContext = Depends(require_admin_ctx)) -> dict:
    require_super(ctx)
    sb = get_supabase()
    if sb.table("stores").select("id").eq("slug", body.slug).limit(1).execute().data:
        raise HTTPException(status_code=409, detail="slug already exists")

    # Same gate PATCH applies (validate_brand) — this route used to write
    # body.brand straight through, so a store could be CREATED with a
    # redirect_url that isn't http(s), contradicting the "server-validated
    # only" assumption RedirectCountdown.tsx's scheme guard exists to not
    # have to rely on alone.
    try:
        validated_brand = validate_brand(body.brand)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = {
        "slug": body.slug,
        "name": body.name,
        "public_key": _gen_public_key(body.slug),
        "shopify_domain": body.shopify_domain,
        "allowed_origins": body.allowed_origins,
        "persona_name": body.persona_name,
        "greeting_template": body.greeting_template,
        "sales_notification_email": body.sales_notification_email,
        "brand": validated_brand,
        "status": "active",
    }
    res = sb.table("stores").insert(row).execute()
    log.info("store_created", slug=body.slug)
    return res.data[0]


@router.get("/admin/stores")
async def list_stores(ctx: AdminContext = Depends(require_admin_ctx)) -> list[dict]:
    sb = get_supabase()
    res = sb.table("stores").select(
        "id, slug, name, public_key, shopify_domain, status, created_at"
    ).order("created_at").execute()
    rows = res.data or []
    if not ctx.is_super:
        allowed = ctx.allowed_store_ids or set()
        rows = [r for r in rows if r["id"] in allowed]
    return rows


@router.post("/admin/stores/{store_id}/sync", status_code=202)
async def sync_store(store_id: str, ctx: AdminContext = Depends(require_admin_ctx)) -> dict:
    """Queue a catalogue refresh for the sidecar's next poll.

    This used to fetch inline and return counts. It cannot any more: the
    backend container's HTTP client is refused by Shopify's edge from a hosting
    ASN (see catalogue_ingest). The fetch happens in the sidecar, so the only
    honest answer here is "queued".
    """
    assert_store_allowed(ctx, store_id)
    store = _load_store(store_id)
    if not store.get("shopify_domain"):
        raise HTTPException(status_code=400, detail="Store has no shopify_domain to sync from")

    catalogue_ingest.enqueue(store_id)
    return {
        "status": "queued",
        "detail": "The catalogue-sync sidecar will fetch this store on its next poll.",
    }


@router.post("/admin/catalogue/sync-all", status_code=202)
async def sync_all_catalogues(ctx: AdminContext = Depends(require_admin_ctx)) -> dict:
    """Queue every syncable store for the sidecar's next poll."""
    require_super(ctx)
    sb = get_supabase()
    rows = sb.table("stores").select("id, shopify_domain, status").execute().data or []
    queued = [r["id"] for r in rows if r.get("shopify_domain") and r.get("status") == "active"]
    for store_id in queued:
        catalogue_ingest.enqueue(store_id)
    return {"status": "queued", "stores": len(queued)}


# --------------------------------------------------------------------------
# Sidecar ingest. These three are called BY the catalogue-sync container, which
# does the fetching this service cannot do itself — see catalogue_ingest for
# the measurements behind that. Plain text where the sidecar has to parse the
# response: that image is busybox with no jq.
# --------------------------------------------------------------------------

@router.get("/admin/catalogue/sync-targets", response_class=PlainTextResponse)
async def catalogue_sync_targets(ctx: AdminContext = Depends(require_admin_ctx)) -> str:
    """Stores due for a fetch right now, one `<store_id> <base_url>` per line.

    Empty body means nothing to do. Handing a target out claims it, so a poll
    that overlaps a still-running fetch will not start the same store twice.
    """
    require_super(ctx)
    targets = catalogue_ingest.claim_targets()
    # EVERY line ends with \n, including the last. POSIX `read` returns
    # non-zero at EOF on an unterminated final line, so the sidecar's
    # `while read` would skip it — silently syncing nothing, with no error to
    # find. Verified in busybox. Pinned by test_sync_targets_are_newline_terminated.
    return "".join(f"{t['store_id']} {t['base']}\n" for t in targets)


@router.post("/admin/stores/{store_id}/catalogue/pages/{page}", response_class=PlainTextResponse)
async def catalogue_ingest_page(
    store_id: str,
    page: int,
    request: Request,
    ctx: AdminContext = Depends(require_admin_ctx),
) -> str:
    """Buffer one fetched page. Body is the raw products.json for that page.

    Returns the product count as plain text; the sidecar compares it to the
    page limit to decide whether to ask for another page.
    """
    require_super(ctx)
    store = _load_store(store_id)
    try:
        payload = json.loads(await request.body())
    except json.JSONDecodeError as exc:
        catalogue_ingest.abandon(store_id)
        raise HTTPException(status_code=400, detail="body is not valid JSON") from exc
    if not isinstance(payload, dict):
        catalogue_ingest.abandon(store_id)
        raise HTTPException(status_code=400, detail="expected a products.json object")
    return str(catalogue_ingest.ingest_page(store, page, payload))


@router.post("/admin/stores/{store_id}/catalogue/commit", response_model=SyncResponse)
async def catalogue_commit(
    store_id: str, ctx: AdminContext = Depends(require_admin_ctx)
) -> dict:
    """Swap the store's catalogue for the buffered pages. Nothing is written
    before this call, so an interrupted fetch leaves the live data alone."""
    require_super(ctx)
    store = _load_store(store_id)
    try:
        return catalogue_ingest.commit(store)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/admin/stores/{store_id}/catalogue/abandon", status_code=204)
async def catalogue_abandon(
    store_id: str, ctx: AdminContext = Depends(require_admin_ctx)
) -> None:
    """Sidecar's fetch failed part way — drop the partial buffer."""
    require_super(ctx)
    catalogue_ingest.abandon(store_id)


@router.get("/admin/catalogue/seconds-until-next-sync", response_class=PlainTextResponse)
async def catalogue_seconds_until_next_sync(
    ctx: AdminContext = Depends(require_admin_ctx),
) -> str:
    """Seconds until the next 00:00 Australia/Sydney — ops introspection.

    Nothing depends on this: the sidecar polls `sync-targets` and the backend
    decides when a store is due. Kept because "when does it next run" is the
    first question anyone asks of a nightly job.
    """
    require_super(ctx)
    return str(seconds_until_next_sync())


@router.get("/admin/stores/{store_id}")
async def get_store_admin(
    store_id: str, request: Request, ctx: AdminContext = Depends(require_admin_ctx)
) -> dict:
    assert_store_allowed(ctx, store_id)
    sb = get_supabase()
    res = sb.table("stores").select("*").eq("id", store_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    row = res.data[0]
    brand = row.get("brand") or {}
    logo_path = brand.get("logo_url")
    if logo_path:
        # Display-only: convert the raw storage path to a signed /media proxy
        # URL. Never mutate the DB row or what PATCH later receives — the
        # frontend strips logo_url before PATCHing, so this is safe.
        row = {**row, "brand": {**brand, "logo_url": media_url(logo_path, str(request.base_url))}}
    return row


@router.patch("/admin/stores/{store_id}")
async def update_store(
    store_id: str, body: UpdateStoreRequest, ctx: AdminContext = Depends(require_admin_ctx)
) -> dict:
    assert_store_allowed(ctx, store_id)
    sb = get_supabase()
    existing_res = sb.table("stores").select("*").eq("id", store_id).limit(1).execute()
    if not existing_res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    existing = existing_res.data[0]

    patch: dict = {}
    if body.brand is not None:
        try:
            validated = validate_brand(body.brand)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        existing_brand = dict(existing.get("brand") or {})
        # Merge, don't replace: keys the client omits (esp. logo_url, and the
        # internal watermark_asset_url) must survive the save. The frontend
        # BrandingView intentionally strips logo_url from the PATCH body and
        # relies on the backend to preserve it.
        patch["brand"] = {**existing_brand, **validated}
    if body.sales_notification_email is not None:
        # Top-level column. Empty/whitespace clears it to NULL; a non-empty
        # value must look like an email. This is the one place the per-store
        # sales inbox is editable after creation.
        email = body.sales_notification_email.strip()
        if email and not _EMAIL_RE.match(email):
            raise HTTPException(status_code=400, detail="Invalid sales notification email")
        patch["sales_notification_email"] = email or None
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = sb.table("stores").update(patch).eq("id", store_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    log.info("store_updated", store_id=store_id)  # no PII (email not logged)
    return res.data[0]


@router.post("/admin/stores/{store_id}/logo")
async def upload_store_logo(
    store_id: str,
    request: Request,
    file: UploadFile = File(...),
    ctx: AdminContext = Depends(require_admin_ctx),
) -> dict:
    assert_store_allowed(ctx, store_id)
    sb = get_supabase()
    res = sb.table("stores").select("*").eq("id", store_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    store = res.data[0]
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    mime = sniff_image_mime(data)
    if mime is None:
        raise HTTPException(status_code=415, detail="Unsupported file type (png/jpeg/gif/webp only)")
    path = upload_asset(data, file.filename or "logo", mime)
    brand = dict(store.get("brand") or {})
    brand["logo_url"] = path
    sb.table("stores").update({"brand": brand}).eq("id", store_id).execute()
    log.info("store_logo_uploaded", store_id=store_id)  # no PII
    return {"logo_url": media_url(path, str(request.base_url))}
