import pytest
from fastapi.testclient import TestClient

from app.services import hat_types as svc


class _Result:
    def __init__(self, data): self.data = data


class _Ins:
    def __init__(self): self.captured = None
    def insert(self, row): self.captured = row; return self
    def execute(self): return _Result([{**self.captured, "id": "sess-1"}])


class _FakeSB:
    def __init__(self): self.ins = _Ins()
    def table(self, name): return self.ins


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("app.api.deps.resolve_store", lambda k: {"id": "s1"} if k else None)
    monkeypatch.setattr(svc, "get_hat_type", lambda hid, store_id=None: {
        "id": hid, "slug": "5p", "name": "5-Panel", "style": "flat",
        "blank_view_images": {"front": "b/front.png", "back": "b/back.png",
                              "left": "b/left.png", "right": "b/right.png"},
        "placement_zones": ["front_panel", "back"], "decoration_types": ["print"],
    })
    fake = _FakeSB()
    monkeypatch.setattr("app.api.routes.sessions.get_supabase", lambda: fake)
    from app.main import create_app
    client = TestClient(create_app())
    client._fake = fake
    return client


def test_blank_session_sets_flow_mode_and_ref(client):
    r = client.post("/sessions/blank",
                    json={"hat_type_id": "h1", "colour": {"name": "Navy", "hex": "#1a2b5c"}},
                    headers={"X-Store-Key": "k"})
    assert r.status_code == 200
    row = client._fake.ins.captured
    assert row["flow_mode"] == "blank"
    assert row["product_ref"]["reference_image_url"] == "b/front.png"
    assert row["collected"]["flow_mode"] == "blank"
    assert row["collected"]["hat_colour"]["hex"] == "#1a2b5c"
    assert row["collected"]["placement_zones"] == ["front_panel", "back"]


def test_blank_session_without_colour_defers_to_chat(client):
    # Landing picker now sends only the hat type; colour is chosen in chat.
    r = client.post("/sessions/blank",
                    json={"hat_type_id": "h1"},
                    headers={"X-Store-Key": "k"})
    assert r.status_code == 200
    row = client._fake.ins.captured
    assert row["flow_mode"] == "blank"
    # No colour seeded yet, so the chat will ask for it (ASK_HAT_COLOUR).
    assert "hat_colour" not in row["collected"]
    assert row["product_ref"]["colour"] == ""
    # The hat type's colourways travel with the session for the in-chat chips.
    assert row["collected"]["hat_colours"] == []  # fixture hat has no colourways
