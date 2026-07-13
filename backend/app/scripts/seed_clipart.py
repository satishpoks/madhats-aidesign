"""Seed a small starter clipart set for a store.

Generates simple, self-authored geometric PNG icons (no external assets, so no
licensing concerns), uploads them to the private bucket, and inserts `clipart`
rows so the customer graphics picker isn't empty on day one. Idempotent: skips a
store that already has clipart.

Run inside the backend container:
    docker compose exec backend python -m app.scripts.seed_clipart
    docker compose exec backend python -m app.scripts.seed_clipart mh_pk_some_other_store
"""
from __future__ import annotations

import io
import math
import sys

from PIL import Image, ImageDraw

from app.services import graphics as svc
from app.services.stores import resolve_store
from app.storage import upload_asset

SIZE = 256
DEFAULT_STORE_KEY = "mh_pk_madhats_local"


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _star_points(cx: float, cy: float, outer: float, inner: float, n: int = 5) -> list[tuple[float, float]]:
    pts = []
    for i in range(n * 2):
        r = outer if i % 2 == 0 else inner
        a = -math.pi / 2 + i * math.pi / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _poly(cx: float, cy: float, r: float, n: int, rot: float = -math.pi / 2) -> list[tuple[float, float]]:
    return [(cx + r * math.cos(rot + i * 2 * math.pi / n), cy + r * math.sin(rot + i * 2 * math.pi / n)) for i in range(n)]


def _icons() -> dict[str, bytes]:
    """Return {name: png_bytes} for the starter set."""
    out: dict[str, bytes] = {}
    c = SIZE / 2

    def save(name: str, img: Image.Image) -> None:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out[name] = buf.getvalue()

    img, d = _canvas(); d.ellipse([40, 40, 216, 216], fill=(37, 99, 235, 255)); save("Circle", img)
    img, d = _canvas(); d.rectangle([48, 48, 208, 208], fill=(16, 185, 129, 255)); save("Square", img)
    img, d = _canvas(); d.polygon(_poly(c, c + 20, 120, 3), fill=(239, 68, 68, 255)); save("Triangle", img)
    img, d = _canvas(); d.polygon(_poly(c, c, 120, 4), fill=(245, 158, 11, 255)); save("Diamond", img)
    img, d = _canvas(); d.polygon(_poly(c, c, 120, 6), fill=(139, 92, 246, 255)); save("Hexagon", img)
    img, d = _canvas(); d.polygon(_star_points(c, c, 120, 50), fill=(234, 179, 8, 255)); save("Star", img)
    # Ring: filled outer circle, punch a transparent inner hole.
    img, d = _canvas(); d.ellipse([40, 40, 216, 216], fill=(14, 165, 233, 255)); d.ellipse([96, 96, 160, 160], fill=(0, 0, 0, 0)); save("Ring", img)
    # Plus/cross from two bars.
    img, d = _canvas(); d.rectangle([104, 48, 152, 208], fill=(220, 38, 38, 255)); d.rectangle([48, 104, 208, 152], fill=(220, 38, 38, 255)); save("Plus", img)
    # Heart: two lobes + a triangle base.
    img, d = _canvas(); d.ellipse([56, 56, 140, 140], fill=(236, 72, 153, 255)); d.ellipse([116, 56, 200, 140], fill=(236, 72, 153, 255)); d.polygon([(64, 118), (192, 118), (128, 210)], fill=(236, 72, 153, 255)); save("Heart", img)
    # Lightning bolt.
    img, d = _canvas(); d.polygon([(150, 30), (80, 140), (120, 140), (100, 226), (180, 110), (135, 110)], fill=(250, 204, 21, 255)); save("Bolt", img)
    # Arrow (right).
    img, d = _canvas(); d.polygon([(40, 104), (150, 104), (150, 64), (216, 128), (150, 192), (150, 152), (40, 152)], fill=(5, 150, 105, 255)); save("Arrow", img)
    # Crown.
    img, d = _canvas(); d.polygon([(48, 180), (48, 90), (96, 130), (128, 70), (160, 130), (208, 90), (208, 180)], fill=(217, 119, 6, 255)); d.rectangle([48, 180, 208, 206], fill=(217, 119, 6, 255)); save("Crown", img)
    return out


def seed_store(store_key: str = DEFAULT_STORE_KEY) -> None:
    store = resolve_store(store_key)
    if not store:
        raise SystemExit(f"Unknown store key: {store_key}")
    existing = svc.list_graphics(store["id"], category="clipart")
    if existing:
        print(f"Store {store_key} already has {len(existing)} clipart items — skipping.")
        return
    icons = _icons()
    for name, png in icons.items():
        path = upload_asset(png, f"clipart_{name.lower()}.png", "image/png")
        svc.create_graphic(store["id"], "clipart", name, path)
        print(f"  + {name}")
    print(f"Seeded {len(icons)} clipart icons for {store_key}.")


if __name__ == "__main__":
    seed_store(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_STORE_KEY)
