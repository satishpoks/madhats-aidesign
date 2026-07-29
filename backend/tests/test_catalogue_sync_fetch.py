"""Catalogue fetch goes through the curl BINARY, and the nightly clock is AEST/AEDT.

Both behaviours exist because of production-only failures that pass in dev:
  - Shopify's Cloudflare edge 429s Python's TLS fingerprint from a hosting ASN
    but accepts curl's from the same host/IP (prod droplet, 2026-07-29).
  - The scheduler sidecar's image has no tzdata, so the midnight clock has to
    be computed backend-side.
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services import catalogue_sync as cs


# --------------------------------------------------------------------------
# fetch: curl binary, not httpx
# --------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self._out, self._err, self.returncode = stdout, stderr, returncode

    async def communicate(self):
        return self._out, self._err


def _curl_stub(stdout: bytes, stderr: bytes = b"", returncode: int = 0):
    """Stand in for asyncio.create_subprocess_exec, recording the argv."""
    seen: dict = {}

    async def _exec(*argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(stdout, stderr, returncode)

    return _exec, seen


def _body(payload: dict, status: str = "200") -> bytes:
    return json.dumps(payload).encode() + b"\n" + status.encode()


@pytest.mark.asyncio
async def test_fetch_shells_out_to_curl_not_httpx(monkeypatch):
    exec_stub, seen = _curl_stub(_body({"products": [{"id": 1}]}))
    monkeypatch.setattr(cs.asyncio, "create_subprocess_exec", exec_stub)

    products = await cs._fetch_products("madhats.com.au")

    assert products == [{"id": 1}]
    assert seen["argv"][0] == "curl"
    assert "https://madhats.com.au/products.json?limit=250&page=1" in seen["argv"]


@pytest.mark.asyncio
async def test_httpx_is_not_imported_by_the_fetch_path():
    """Guard: reintroducing httpx here reinstates the production 429."""
    src = (cs.__file__).replace(".pyc", ".py")
    with open(src, encoding="utf-8") as fh:
        code = fh.read()
    assert "import httpx" not in code
    assert "httpx.AsyncClient" not in code


@pytest.mark.asyncio
async def test_non_200_raises_with_the_status(monkeypatch):
    exec_stub, _ = _curl_stub(_body({}, status="429"))
    monkeypatch.setattr(cs.asyncio, "create_subprocess_exec", exec_stub)

    with pytest.raises(cs.CatalogueFetchError, match="429"):
        await cs._fetch_products("madhats.com.au")


@pytest.mark.asyncio
async def test_curl_failure_surfaces_stderr(monkeypatch):
    exec_stub, _ = _curl_stub(b"", stderr=b"curl: (6) Could not resolve host", returncode=6)
    monkeypatch.setattr(cs.asyncio, "create_subprocess_exec", exec_stub)

    with pytest.raises(cs.CatalogueFetchError, match="Could not resolve host"):
        await cs._fetch_products("nope.invalid")


@pytest.mark.asyncio
async def test_missing_curl_binary_says_so(monkeypatch):
    async def _boom(*a, **k):
        raise FileNotFoundError("curl")

    monkeypatch.setattr(cs.asyncio, "create_subprocess_exec", _boom)
    with pytest.raises(cs.CatalogueFetchError, match="Dockerfile"):
        await cs._fetch_products("madhats.com.au")


@pytest.mark.asyncio
async def test_pagination_stops_on_a_short_page(monkeypatch):
    pages = [
        _body({"products": [{"id": i} for i in range(cs._PAGE_LIMIT)]}),
        _body({"products": [{"id": 9001}]}),        # short -> last page
    ]
    calls = {"n": 0}

    async def _exec(*argv, **kwargs):
        out = pages[calls["n"]]
        calls["n"] += 1
        return _FakeProc(out)

    monkeypatch.setattr(cs.asyncio, "create_subprocess_exec", _exec)
    products = await cs._fetch_products("madhats.com.au")

    assert calls["n"] == 2
    assert len(products) == cs._PAGE_LIMIT + 1


# --------------------------------------------------------------------------
# nightly clock
# --------------------------------------------------------------------------

SYD = ZoneInfo("Australia/Sydney")


def test_seconds_until_next_sync_counts_to_local_midnight():
    now = datetime(2026, 7, 29, 23, 0, tzinfo=SYD)
    assert cs.seconds_until_next_sync(now) == 3600


def test_clock_is_sydney_not_utc():
    """23:00 Sydney is 13:00 UTC — a UTC clock would answer 39600, not 3600."""
    now = datetime(2026, 7, 29, 13, 0, tzinfo=ZoneInfo("UTC"))
    assert cs.seconds_until_next_sync(now) == 3600


def test_dst_transition_night_is_still_one_midnight():
    """AEDT starts 2026-10-04; the night before is 23h, not 24h."""
    now = datetime(2026, 10, 3, 0, 0, tzinfo=SYD)
    assert cs.seconds_until_next_sync(now) == 24 * 3600
    assert cs.seconds_until_next_sync(datetime(2026, 10, 4, 0, 0, tzinfo=SYD)) == 23 * 3600


def test_never_returns_zero():
    now = datetime(2026, 7, 29, 23, 59, 59, 999_000, tzinfo=SYD)
    assert cs.seconds_until_next_sync(now) >= 1
