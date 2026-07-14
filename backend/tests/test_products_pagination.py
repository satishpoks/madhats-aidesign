"""Tests for paginated GET /products endpoint.

TDD: these tests are written before the implementation and should fail initially.
They cover:
  - ProductPage model shape
  - list_products() service signature and clamping
  - Route query-param wiring (via TestClient + mocked service)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.data.stub_catalogue import STUB_PRODUCTS
from app.models.product import Product, ProductPage


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_product_page_model_shape():
    page = ProductPage(
        items=[],
        total=0,
        limit=50,
        offset=0,
    )
    assert page.total == 0
    assert page.limit == 50
    assert page.offset == 0
    assert page.items == []


def test_product_page_model_with_items():
    stub = STUB_PRODUCTS[0]
    product = Product(**stub)
    page = ProductPage(items=[product], total=6, limit=2, offset=0)
    assert len(page.items) == 1
    assert page.total == 6


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


def _make_supabase_mock(rows: list[dict], total: int):
    """Return a mock supabase client that simulates count+range responses."""

    class _Resp:
        data = rows
        count = total

    class _Query:
        def eq(self, *a, **kw):
            return self

        def order(self, *a, **kw):
            return self

        def range(self, *a, **kw):
            return self

        def execute(self):
            return _Resp()

    class _Table:
        def select(self, *a, **kw):
            return _Query()

    class _Client:
        def table(self, name):
            return _Table()

    return _Client()


def test_list_products_returns_tuple():
    from app.services import products as svc

    mock_sb = _make_supabase_mock(STUB_PRODUCTS[:2], 6)
    with patch("app.services.products.get_supabase", return_value=mock_sb):
        result = svc.list_products(store_id="store-1", limit=2, offset=0)
    assert isinstance(result, tuple)
    assert len(result) == 4
    items, total, used_limit, used_offset = result
    assert isinstance(items, list)
    assert isinstance(total, int)
    assert isinstance(used_limit, int)
    assert isinstance(used_offset, int)


def test_list_products_clamps_limit_max():
    from app.services import products as svc

    mock_sb = _make_supabase_mock([], 0)
    with patch("app.services.products.get_supabase", return_value=mock_sb):
        items, total, used_limit, used_offset = svc.list_products(store_id="s", limit=999, offset=0)
    # offset=0 + no data => falls back to stub
    assert total == len(STUB_PRODUCTS)
    assert used_limit == 200


def test_list_products_clamps_limit_min():
    from app.services import products as svc

    mock_sb = _make_supabase_mock(STUB_PRODUCTS[:1], 6)
    with patch("app.services.products.get_supabase", return_value=mock_sb):
        items, total, used_limit, used_offset = svc.list_products(store_id="s", limit=0, offset=0)
    # limit should be clamped to at least 1
    assert total == 6
    assert len(items) == 1
    assert used_limit == 1


def test_list_products_clamps_offset_negative():
    from app.services import products as svc

    mock_sb = _make_supabase_mock(STUB_PRODUCTS[:2], 6)
    with patch("app.services.products.get_supabase", return_value=mock_sb):
        # Should not raise; negative offset is silently clamped to 0
        items, total, used_limit, used_offset = svc.list_products(store_id="s", limit=2, offset=-5)
    assert total == 6
    assert used_offset == 0


def test_list_products_stub_fallback_at_offset_0():
    """When DB returns empty rows and offset==0, return stub catalogue."""
    from app.services import products as svc

    mock_sb = _make_supabase_mock([], 0)
    with patch("app.services.products.get_supabase", return_value=mock_sb):
        items, total, used_limit, used_offset = svc.list_products(store_id=None, limit=50, offset=0)
    assert len(items) == len(STUB_PRODUCTS)
    assert total == len(STUB_PRODUCTS)


def test_list_products_no_stub_fallback_at_nonzero_offset():
    """When DB returns empty rows but offset > 0, return empty (not stub)."""
    from app.services import products as svc

    mock_sb = _make_supabase_mock([], 0)
    with patch("app.services.products.get_supabase", return_value=mock_sb):
        items, total, used_limit, used_offset = svc.list_products(store_id=None, limit=50, offset=10)
    assert items == []
    assert total == 0


def test_list_products_clamps_limit_to_db_range():
    """DB-path: .range() is called with clamped bounds; returned used_limit == 200."""
    from app.services import products as svc

    real_rows = STUB_PRODUCTS[:1]
    captured_range: list = []

    class _Resp:
        data = real_rows
        count = 10

    class _Query:
        def eq(self, *a, **kw):
            return self

        def order(self, *a, **kw):
            return self

        def range(self, start, end):
            captured_range.append((start, end))
            return self

        def execute(self):
            return _Resp()

    class _Table:
        def select(self, *a, **kw):
            return _Query()

    class _Client:
        def table(self, name):
            return _Table()

    with patch("app.services.products.get_supabase", return_value=_Client()):
        items, total, used_limit, used_offset = svc.list_products(
            store_id="s", limit=999, offset=0
        )

    # Clamp must be applied before the DB call.
    assert used_limit == 200
    assert len(captured_range) == 1, "range() should be called exactly once"
    # limit 200 → range(0, 199)  i.e. (offset, offset + limit - 1)
    assert captured_range[0] == (0, 199)


# ---------------------------------------------------------------------------
# get_product() resolver tests — UUID vs Shopify product id
# ---------------------------------------------------------------------------


def _make_getproduct_mock(rows: list[dict]):
    """Mock supabase client that records the column used in the .eq() lookup."""
    captured: dict = {}

    class _Resp:
        data = rows

    class _Query:
        def eq(self, column, value):
            # First eq() is the id/shopify lookup; record it.
            captured.setdefault("column", column)
            captured.setdefault("value", value)
            return self

        def limit(self, *a, **kw):
            return self

        def execute(self):
            return _Resp()

    class _Table:
        def select(self, *a, **kw):
            return _Query()

    class _Client:
        def table(self, name):
            return _Table()

    return _Client(), captured


def test_get_product_numeric_id_resolves_by_shopify_product_id():
    """A numeric id (a Shopify {{ product.id }}) is looked up on shopify_product_id."""
    from app.services import products as svc

    row = {"id": "uuid-abc", "name": "Cap"}
    mock_sb, captured = _make_getproduct_mock([row])
    with patch("app.services.products.get_supabase", return_value=mock_sb):
        result = svc.get_product("8123456789", store_id="s")
    assert result == row
    assert captured["column"] == "shopify_product_id"
    assert captured["value"] == "8123456789"


def test_get_product_uuid_resolves_by_id():
    """A UUID id keeps resolving against the internal id column (unchanged)."""
    from app.services import products as svc

    row = {"id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301", "name": "Cap"}
    mock_sb, captured = _make_getproduct_mock([row])
    with patch("app.services.products.get_supabase", return_value=mock_sb):
        result = svc.get_product("3f2504e0-4f89-11d3-9a0c-0305e82c3301", store_id="s")
    assert result == row
    assert captured["column"] == "id"


# ---------------------------------------------------------------------------
# Route tests (via TestClient)
# ---------------------------------------------------------------------------

_FAKE_STORE = {"id": "store-test-123", "name": "Test Store", "store_key": "mh_pk_madhats_local"}


def _make_app():
    """Construct just enough of the FastAPI app for product route testing."""
    from app.api.deps import require_store
    from app.main import app

    # Override require_store so route tests don't hit the real DB
    app.dependency_overrides[require_store] = lambda: _FAKE_STORE
    return app


@pytest.fixture()
def client():
    """TestClient with store auth dependency overridden (all requests pass auth)."""
    app = _make_app()
    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        # Clean up overrides so other tests using the global app aren't affected
        app.dependency_overrides.clear()


@pytest.fixture()
def unauth_client():
    """TestClient with NO dependency override — require_store enforces auth normally."""
    from app.main import app

    # Ensure require_store override is cleared
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


_STORE_HEADERS = {"X-Store-Key": "mh_pk_madhats_local"}

_PAGE_ITEMS = STUB_PRODUCTS[:2]
_PAGE_TOTAL = 6


def _patch_list(items=_PAGE_ITEMS, total=_PAGE_TOTAL, used_limit=50, used_offset=0):
    return patch(
        "app.services.products.list_products",
        return_value=(items, total, used_limit, used_offset),
    )


def test_route_returns_product_page(client):
    with _patch_list():
        resp = client.get("/products?limit=2&offset=0", headers=_STORE_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert "limit" in body
    assert "offset" in body


def test_route_reflects_limit_and_offset(client):
    with _patch_list(used_limit=2, used_offset=0):
        resp = client.get("/products?limit=2&offset=0", headers=_STORE_HEADERS)
    body = resp.json()
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert body["total"] == _PAGE_TOTAL
    assert len(body["items"]) == len(_PAGE_ITEMS)


def test_route_offset_page(client):
    page2_items = STUB_PRODUCTS[2:4]
    with _patch_list(items=page2_items, total=6, used_limit=2, used_offset=2):
        resp = client.get("/products?limit=2&offset=2", headers=_STORE_HEADERS)
    body = resp.json()
    assert body["offset"] == 2
    assert len(body["items"]) == 2


def test_route_clamped_limit_reflected(client):
    """Route envelope must reflect the clamped limit the service actually used."""
    # The service receives limit=999, clamps to 200, and returns used_limit=200.
    # The route must put that value in the envelope (no re-derivation in the route).
    two_hundred = STUB_PRODUCTS * 34  # enough items to fill 200 slots
    with _patch_list(items=two_hundred[:200], total=1000, used_limit=200):
        resp = client.get("/products?limit=999&offset=0", headers=_STORE_HEADERS)
    body = resp.json()
    assert body["limit"] == 200


def test_route_unauthorized_without_header(unauth_client):
    """Missing X-Store-Key header must produce 401 (no dependency override)."""
    resp = unauth_client.get("/products")
    assert resp.status_code == 401


def test_route_product_id_unchanged(client):
    """GET /products/{id} still returns a single Product, not a page."""
    from app.services import products as svc

    stub = STUB_PRODUCTS[0]
    with patch.object(svc, "get_product", return_value=stub):
        resp = client.get(f"/products/{stub['id']}", headers=_STORE_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    # Single product — no pagination envelope
    assert "id" in body
    assert "items" not in body
