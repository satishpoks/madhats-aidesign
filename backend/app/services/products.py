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
) -> tuple[list[dict], int]:
    """Return a page of products and the total matching count.

    ``limit`` is clamped to [1, 200]; ``offset`` is clamped to >= 0.
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
        return res.data, (res.count or 0)

    if offset == 0:
        log.info("catalogue_empty_using_stub")
        return STUB_PRODUCTS, len(STUB_PRODUCTS)

    return [], 0


def get_product(product_id: str, store_id: str | None = None) -> dict | None:
    sb = get_supabase()
    query = sb.table("product_references").select(_COLUMNS).eq("id", product_id)
    if store_id:
        query = query.eq("store_id", store_id)
    res = query.limit(1).execute()
    if res.data:
        return res.data[0]
    return _stub_get(product_id)
