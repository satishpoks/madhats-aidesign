from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import require_store
from app.models.product import Product, ProductPage
from app.services import products as products_service

router = APIRouter(tags=["products"])


@router.get("/products", response_model=ProductPage)
async def list_products(
    store: dict = Depends(require_store),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
) -> ProductPage:
    # Pass raw values; clamping (limit→[1,200], offset→>=0) is enforced inside
    # the service, which is the single source of truth.  We reflect the values
    # the service actually used rather than recomputing them here.
    items, total, used_limit, used_offset = products_service.list_products(
        store_id=store["id"],
        limit=limit,
        offset=offset,
    )
    return ProductPage(
        items=items,
        total=total,
        limit=used_limit,
        offset=used_offset,
    )


@router.get("/products/{product_id}", response_model=Product)
async def get_product_detail(product_id: str, store: dict = Depends(require_store)) -> dict:
    product = products_service.get_product(product_id, store_id=store["id"])
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product
