import pytest
from fastapi.testclient import TestClient

from app.services import composite


class _Result:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, rows): self._rows = rows; self._patch = None
    def select(self, *a, **k): return self
    def eq(self, f, v):
        self._rows = [r for r in self._rows if r.get(f) == v]; return self
    def limit(self, n): self._rows = self._rows[:n]; return self
    def update(self, patch): self._patch = patch; return self
    def execute(self): return _Result(self._rows)


class _SB:
    def __init__(self, rows): self._rows = rows
    def table(self, n): return _Q(list(self._rows))


@pytest.fixture()
def client(monkeypatch):
    session = {"id": "s1", "product_ref": {"view_images": {
        "front": "b/f", "back": "b/b", "left": "b/l", "right": "b/r"}},
        "collected": {"hat_colour": {"hex": "#1a2b5c"}, "elements": []}}
    monkeypatch.setattr("app.api.routes.composite.get_supabase", lambda: _SB([session]))
    monkeypatch.setattr(composite, "render_composite_views",
                        lambda vp, hexc, els: {"front": "composite/f.png"})
    from app.main import create_app
    return TestClient(create_app())


def test_composite_returns_proxied_urls(client):
    r = client.post("/composite/s1")
    assert r.status_code == 200
    assert "/media/" in r.json()["views"]["front"]


def test_composite_missing_session_404(client):
    assert client.post("/composite/nope").status_code == 404


def test_composite_render_failure_returns_200_graceful(client, monkeypatch):
    def _raise(vp, hexc, els):
        raise RuntimeError("boom")

    monkeypatch.setattr(composite, "render_composite_views", _raise)
    r = client.post("/composite/s1")
    assert r.status_code == 200
    assert r.json() == {"views": {}, "error": "composite_failed"}
