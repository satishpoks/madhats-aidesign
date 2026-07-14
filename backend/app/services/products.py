"""Product catalogue access — reads from the product_references table.

Falls back to the in-code stub catalogue only if the table is empty (e.g. a
fresh DB with no seed), so local dev never shows an empty picker.
"""
from __future__ import annotations

import structlog

from app.data.stub_catalogue import STUB_PRODUCTS
from app.data.stub_catalogue import get_product as _stub_get
from app.db import get_supabase

log = structlog.get_logger()

_COLUMNS = (
    "id, style, colour, name, description, store_url, "
    "reference_image_url, view_images, placement_zones, decoration_types"
)


def list_products(
    store_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int, int, int]:
    """Return (items, total, used_limit, used_offset).

    ``limit`` is clamped to [1, 200]; ``offset`` is clamped to >= 0.
    The clamped values are returned as the third and fourth elements so
    callers never need to re-derive them — the service is the single source
    of truth for what was actually used.

    Falls back to the in-code stub catalogue when the DB returns no rows
    *and* ``offset == 0`` (i.e. the first page of an empty table).
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    sb = get_supabase()
    query = sb.table("product_references").select(_COLUMNS, count="exact")
    if store_id:
        query = query.eq("store_id", store_id)
    res = query.order("name").range(offset, offset + limit - 1).execute()

    if res.data:
        return res.data, (res.count or 0), limit, offset

    if offset == 0:
        log.info("catalogue_empty_using_stub")
        return STUB_PRODUCTS, len(STUB_PRODUCTS), limit, offset

    return [], 0, limit, offset


def get_product(product_id: str, store_id: str | None = None) -> dict | None:
    """Resolve a product by internal UUID or by Shopify product id.

    The internal ``id`` is a ``gen_random_uuid()`` that is regenerated on every
    catalogue re-sync (sync does delete+insert), so it is unstable. A Shopify
    storefront button only knows ``{{ product.id }}`` — the numeric Shopify
    product id — which we persist as the stable ``shopify_product_id``. So a
    purely numeric id is looked up against ``shopify_product_id``; anything else
    (a UUID) is looked up against ``id`` as before. Querying the ``uuid`` column
    with a numeric string would otherwise raise a Postgres type error.
    """
    column = "shopify_product_id" if product_id.isdigit() else "id"
    sb = get_supabase()
    query = sb.table("product_references").select(_COLUMNS).eq(column, product_id)
    if store_id:
        query = query.eq("store_id", store_id)
    res = query.limit(1).execute()
    if res.data:
        return res.data[0]
    return _stub_get(product_id)
