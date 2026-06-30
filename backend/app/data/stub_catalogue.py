"""Stub product catalogue for the prototype.

Replaced by Shopify sync into product_references in the Standard tier. Reference
image URLs are placeholders; every generation composites onto the selected colour's
reference_image_url.
"""
from __future__ import annotations


def _ph(text: str, bg: str = "1f2937") -> str:
    return f"https://placehold.co/600x450/{bg}/ffffff?text={text.replace(' ', '+')}"


STUB_PRODUCTS: list[dict] = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "style": "snapback",
        "colour": "black",
        "name": "Classic Snapback — Black",
        "reference_image_url": _ph("Black Snapback"),
        "view_images": {
            "front": _ph("Snapback Front"),
            "side": _ph("Snapback Side"),
            "back": _ph("Snapback Back"),
        },
        "placement_zones": ["front_panel", "side", "back"],
        "decoration_types": ["print", "embroidery"],
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "style": "dad_hat",
        "colour": "navy",
        "name": "Dad Hat — Navy",
        "reference_image_url": _ph("Navy Dad Hat", "1e3a8a"),
        "view_images": {
            "front": _ph("Dad Hat Front", "1e3a8a"),
            "side": _ph("Dad Hat Side", "1e3a8a"),
            "back": _ph("Dad Hat Back", "1e3a8a"),
        },
        "placement_zones": ["front_panel", "side", "back", "under_brim"],
        "decoration_types": ["print", "embroidery"],
    },
    {
        "id": "33333333-3333-3333-3333-333333333333",
        "style": "trucker",
        "colour": "white_black",
        "name": "Trucker Cap — White/Black",
        "reference_image_url": _ph("Trucker Cap", "374151"),
        "view_images": {
            "front": _ph("Trucker Front", "374151"),
            "side": _ph("Trucker Side", "374151"),
            "back": _ph("Trucker Mesh Back", "374151"),
        },
        "placement_zones": ["front_panel", "side"],
        "decoration_types": ["print", "embroidery", "patch"],
    },
    {
        "id": "44444444-4444-4444-4444-444444444444",
        "style": "beanie",
        "colour": "charcoal",
        "name": "Cuffed Beanie — Charcoal",
        "reference_image_url": _ph("Charcoal Beanie", "334155"),
        "view_images": {
            "front": _ph("Beanie Front", "334155"),
            "side": _ph("Beanie Side", "334155"),
        },
        "placement_zones": ["front_panel", "side"],
        "decoration_types": ["embroidery", "patch"],
    },
    {
        "id": "55555555-5555-5555-5555-555555555555",
        "style": "five_panel",
        "colour": "olive",
        "name": "Five Panel — Olive",
        "reference_image_url": _ph("Olive Five Panel", "3f6212"),
        "view_images": {
            "front": _ph("Five Panel Front", "3f6212"),
            "side": _ph("Five Panel Side", "3f6212"),
            "back": _ph("Five Panel Back", "3f6212"),
        },
        "placement_zones": ["front_panel", "side", "back"],
        "decoration_types": ["print", "embroidery"],
    },
    {
        "id": "66666666-6666-6666-6666-666666666666",
        "style": "bucket_hat",
        "colour": "khaki",
        "name": "Bucket Hat — Khaki",
        "reference_image_url": _ph("Khaki Bucket Hat", "78716c"),
        "view_images": {
            "front": _ph("Bucket Front", "78716c"),
            "side": _ph("Bucket Side", "78716c"),
        },
        "placement_zones": ["front_panel", "side"],
        "decoration_types": ["print", "embroidery"],
    },
]

_BY_ID = {p["id"]: p for p in STUB_PRODUCTS}


def get_product(product_id: str) -> dict | None:
    return _BY_ID.get(product_id)
