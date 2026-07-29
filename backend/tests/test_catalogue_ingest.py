"""Sidecar ingest: buffer pages, commit once, never half-wipe a catalogue.

The backend cannot fetch the Shopify feed itself (its HTTP client is refused
from a hosting ASN — see catalogue_ingest's docstring), so the sidecar fetches
and posts pages here. The invariant that matters: product_references is written
exactly once, at commit, so an interrupted fetch leaves the live catalogue
alone.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services import catalogue_ingest as ci

SYD = ZoneInfo("Australia/Sydney")
STORE = {"id": "store-1", "shopify_domain": "madhats.com.au"}


def _page(n: int, start: int = 0) -> dict:
    return {
        "products": [
            {
                "id": start + i,
                "handle": f"cap-{start + i}",
                "title": f"Cap {start + i}",
                "images": [{"src": f"https://x/cap-{start + i}.jpg"}],
            }
            for i in range(n)
        ]
    }


@pytest.fixture(autouse=True)
def _clean():
    ci.reset_state()
    yield
    ci.reset_state()


@pytest.fixture
def written(monkeypatch):
    """Capture replace_catalogue calls instead of touching the database."""
    calls: list = []

    def _replace(store_id, rows, *, fetched):
        calls.append({"store_id": store_id, "rows": rows, "fetched": fetched})
        return {"fetched": fetched, "imported": len(rows), "skipped": fetched - len(rows)}

    monkeypatch.setattr(ci, "replace_catalogue", _replace)
    return calls


# ------------------------------------------------------------------ ingest

def test_pages_accumulate_and_commit_writes_once(written):
    assert ci.ingest_page(STORE, 1, _page(250)) == 250
    assert ci.ingest_page(STORE, 2, _page(30, start=250)) == 30
    assert written == []                      # nothing written yet — the point

    result = ci.commit(STORE)

    assert len(written) == 1
    assert written[0]["fetched"] == 280
    assert result["imported"] == 280


def test_an_abandoned_fetch_never_writes(written):
    ci.ingest_page(STORE, 1, _page(250))
    ci.abandon(STORE["id"])

    with pytest.raises(LookupError):
        ci.commit(STORE)
    assert written == []                      # live catalogue untouched


def test_commit_without_any_pages_is_refused(written):
    with pytest.raises(LookupError):
        ci.commit(STORE)
    assert written == []


def test_empty_feed_is_refused_rather_than_wiping(written):
    """An empty feed is far likelier to be a broken fetch than a real catalogue."""
    ci.ingest_page(STORE, 1, {"products": []})
    with pytest.raises(ValueError, match="empty"):
        ci.commit(STORE)
    assert written == []


def test_page_one_restarts_the_buffer(written):
    ci.ingest_page(STORE, 1, _page(5))
    ci.ingest_page(STORE, 2, _page(5, start=5))
    ci.ingest_page(STORE, 1, _page(3))        # a fresh run begins
    ci.commit(STORE)
    assert written[0]["fetched"] == 3


def test_products_without_images_are_skipped_not_imported(written):
    ci.ingest_page(STORE, 1, {"products": [{"id": 1, "handle": "a", "title": "A", "images": []}]})
    with pytest.raises(ValueError):           # nothing importable -> refuse
        ci.commit(STORE)


# ------------------------------------------------------- targets & schedule

@pytest.fixture
def stores(monkeypatch):
    rows = [
        {"id": "s1", "slug": "a", "shopify_domain": "a.example", "status": "active"},
        {"id": "s2", "slug": "b", "shopify_domain": "b.example", "status": "active"},
        {"id": "s3", "slug": "c", "shopify_domain": None, "status": "active"},
        {"id": "s4", "slug": "d", "shopify_domain": "d.example", "status": "disabled"},
    ]
    monkeypatch.setattr(ci, "_syncable_stores", lambda: [
        r for r in rows if r["shopify_domain"] and r["status"] == "active"
    ])
    return rows


def test_nothing_is_due_until_queued_or_midnight(stores):
    assert ci.claim_targets(datetime(2026, 7, 29, 12, 0, tzinfo=SYD)) == []


def test_queued_store_is_handed_out_with_a_normalised_base(stores):
    ci.enqueue("s1")
    targets = ci.claim_targets(datetime(2026, 7, 29, 12, 0, tzinfo=SYD))
    assert targets == [{"store_id": "s1", "base": "https://a.example"}]


def test_a_claimed_target_is_not_handed_out_twice(stores):
    ci.enqueue("s1")
    first = ci.claim_targets(datetime(2026, 7, 29, 12, 0, tzinfo=SYD))
    second = ci.claim_targets(datetime(2026, 7, 29, 12, 0, tzinfo=SYD))
    assert first and second == []             # still in flight


def test_commit_releases_the_claim_and_the_queue(stores, written):
    ci.enqueue("s1")
    ci.claim_targets(datetime(2026, 7, 29, 12, 0, tzinfo=SYD))
    ci.ingest_page({"id": "s1", "shopify_domain": "a.example"}, 1, _page(2))
    ci.commit({"id": "s1", "shopify_domain": "a.example"})
    assert "s1" not in ci._queued and "s1" not in ci._claims


def test_restart_does_not_trigger_an_immediate_full_sync(stores):
    """First poll only arms the date — otherwise every deploy refreshes everything."""
    assert ci.claim_targets(datetime(2026, 7, 29, 0, 5, tzinfo=SYD)) == []


def test_date_rollover_queues_every_syncable_store(stores):
    ci.claim_targets(datetime(2026, 7, 29, 23, 55, tzinfo=SYD))     # arm
    targets = ci.claim_targets(datetime(2026, 7, 30, 0, 1, tzinfo=SYD))
    assert sorted(t["store_id"] for t in targets) == ["s1", "s2"]   # s3/s4 excluded


def test_sync_targets_are_newline_terminated(stores):
    """Every line, including the last.

    POSIX `read` returns non-zero at EOF on an unterminated final line, so the
    sidecar's `while read` loop skips it. With one store queued that means the
    nightly sync does NOTHING, silently, with no error anywhere. Verified in
    busybox; this shipped and was caught only by running the real sidecar.
    """
    import asyncio  # noqa: PLC0415

    from app.api.deps import AdminContext  # noqa: PLC0415
    from app.api.routes.admin_stores import catalogue_sync_targets  # noqa: PLC0415

    ci.enqueue("s1")
    super_ctx = AdminContext(user_id=None, email=None, is_super=True, allowed_store_ids=None)
    body = asyncio.run(catalogue_sync_targets(super_ctx))

    assert body == "s1 https://a.example\n"
    assert body.endswith("\n")


def test_midnight_fires_once_per_local_day(stores):
    ci.claim_targets(datetime(2026, 7, 29, 23, 55, tzinfo=SYD))
    ci.claim_targets(datetime(2026, 7, 30, 0, 1, tzinfo=SYD))       # fires
    ci._claims.clear()                                              # pretend runs finished
    ci._queued.clear()
    assert ci.claim_targets(datetime(2026, 7, 30, 3, 0, tzinfo=SYD)) == []
