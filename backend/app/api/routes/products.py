from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import require_store
from app.models.product import Product, ProductPage
from app.services import products as products_service

router = APIRouter(tags=["products"])


@router.get("/products", response_model=ProductPage)
async def list_products(
    store: dict = Depends(require_store),
    limit: int = Query(default=50, ge=1),
    offset: int = Query(default=0, ge=0),
) -> ProductPage:
    # Pass raw values; clamping is enforced inside the service.
    items, total = products_service.list_products(
        store_id=store["id"],
        limit=limit,
        offset=offset,
    )
    # Reflect the clamped values actually used by the service.
    clamped_limit = max(1, min(limit, 200))
    clamped_offset = max(0, offset)
    return ProductPage(
        items=items,
        total=total,
        limit=clamped_limit,
        offset=clamped_offset,
    )


@router.get("/products/{product_id}", response_model=Product)
async def get_product_detail(product_id: str, store: dict = Depends(require_store)) -> dict:
    product = products_service.get_product(product_id, store_id=store["id"])
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product
