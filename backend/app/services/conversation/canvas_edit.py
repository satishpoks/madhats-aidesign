"""Turn a described change into canvas ops — the arithmetic half.

Split deliberately: `intent_extractor.interpret_canvas_edit` asks Haiku WHAT the
customer wants, from a closed vocabulary, and this module works out the numbers.
The model never emits a coordinate. That extends v2's existing stance — the LLM
reads the customer, it never routes — to: it never computes geometry. Everything
here is a pure function of plain dicts, so it needs no LLM and no Supabase.
"""
from __future__ import annotations

# Normalised (0-1) stage units.
AMOUNTS: dict[str, float] = {"small": 0.05, "medium": 0.10, "large": 0.20}
SCALES: dict[str, float] = {"small": 1.15, "medium": 1.35, "large": 1.70}
ROTATIONS: dict[str, float] = {"small": 5.0, "medium": 15.0, "large": 45.0}
CURVES: dict[str, int] = {"up": 40, "down": -40, "none": 0}

# Small on purpose: an unresolvable colour is DROPPED, not guessed at.
NAMED_COLOURS: dict[str, str] = {
    "white": "#ffffff", "black": "#111827", "red": "#dc2626", "blue": "#2563eb",
    "navy": "#1e3a8a", "green": "#16a34a", "yellow": "#facc15",
    "orange": "#ea580c", "purple": "#9333ea", "pink": "#ec4899",
    "grey": "#6b7280", "gray": "#6b7280",
}

_MOVE = {"up": (0.0, -1.0), "down": (0.0, 1.0), "left": (-1.0, 0.0), "right": (1.0, 0.0)}
# Which field carries "the colour" depends on the element type.
_COLOUR_FIELD = {"text": "colour", "shape": "fill", "drawing": "stroke"}
_TEXT_ONLY = {"set_text", "font", "curve"}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _describe(el: dict) -> str:
    t = el.get("type")
    if t == "text":
        return f'the text "{el.get("content") or ""}"'
    if t == "image":
        return "the uploaded logo/artwork"
    if t == "shape":
        return f'the {el.get("shapeKind") or "shape"}'
    return "the hand-drawn line"


def inventory(canvas_design: dict) -> list[dict]:
    """Every element the customer can refer to. Ids are a closed set we own, so
    validating the model's choice is an identity lookup."""
    out: list[dict] = []
    for face, els in (canvas_design.get("faces") or {}).items():
        for el in els or []:
            if not el.get("id"):
                continue
            out.append({"id": el["id"], "face": face,
                        "type": el.get("type") or "", "description": _describe(el)})
    return out


def _index(canvas_design: dict) -> dict[str, tuple[str, dict]]:
    idx: dict[str, tuple[str, dict]] = {}
    for face, els in (canvas_design.get("faces") or {}).items():
        for el in els or []:
            if el.get("id"):
                idx[el["id"]] = (face, el)
    return idx


def _colour(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    v = raw.strip().lower()
    if v.startswith("#") and len(v) == 7:
        return v
    return NAMED_COLOURS.get(v)


def _patch_for(op: dict, el: dict) -> dict | None:
    """The patch one op implies, or None to drop it. Never mutates `el`."""
    kind = op.get("op")
    etype = el.get("type")

    if kind in _TEXT_ONLY and etype != "text":
        return None

    if kind == "move":
        step = AMOUNTS.get(op.get("amount") or "")
        vec = _MOVE.get(op.get("direction") or "")
        if step is None or vec is None:
            return None
        w = float(el.get("width") or 0.0)
        h = float(el.get("height") or 0.0)
        patch: dict = {}
        if vec[0]:
            patch["x"] = _clamp(float(el.get("x") or 0.0) + vec[0] * step, 0.0, max(0.0, 1.0 - w))
        if vec[1]:
            patch["y"] = _clamp(float(el.get("y") or 0.0) + vec[1] * step, 0.0, max(0.0, 1.0 - h))
        return patch

    if kind == "resize":
        scale = SCALES.get(op.get("amount") or "")
        direction = op.get("direction")
        if scale is None or direction not in ("bigger", "smaller"):
            return None
        if direction == "smaller":
            scale = 1.0 / scale
        w, h = float(el.get("width") or 0.0), float(el.get("height") or 0.0)
        cx = float(el.get("x") or 0.0) + w / 2
        cy = float(el.get("y") or 0.0) + h / 2
        nw, nh = _clamp(w * scale, 0.02, 1.0), _clamp(h * scale, 0.02, 1.0)
        return {"width": nw, "height": nh,
                "x": _clamp(cx - nw / 2, 0.0, max(0.0, 1.0 - nw)),
                "y": _clamp(cy - nh / 2, 0.0, max(0.0, 1.0 - nh))}

    if kind == "rotate":
        deg = ROTATIONS.get(op.get("amount") or "")
        direction = op.get("direction")
        if deg is None or direction not in ("clockwise", "anticlockwise"):
            return None
        if direction == "anticlockwise":
            deg = -deg
        return {"rotation": (float(el.get("rotation") or 0.0) + deg) % 360}

    if kind == "recolour":
        hexv = _colour(op.get("colour"))
        field = _COLOUR_FIELD.get(etype or "")
        if hexv is None or field is None:
            return None
        return {field: hexv}

    if kind == "set_text":
        text = (op.get("text") or "").strip()
        return {"content": text[:120]} if text else None

    if kind == "font":
        font = (op.get("font") or "").strip()
        return {"font": font[:60]} if font else None

    if kind == "curve":
        curve = CURVES.get(op.get("direction") or "")
        return None if curve is None else {"curve": curve}

    return None


def resolve_ops(raw_ops: list[dict], canvas_design: dict) -> list[dict]:
    """Closed-vocabulary intent -> canvas_ops. Anything unrecognised is dropped,
    never guessed at: a wrong nudge lands on a design the customer approved."""
    idx = _index(canvas_design)
    out: list[dict] = []
    for op in raw_ops or []:
        if not isinstance(op, dict):
            continue
        found = idx.get(op.get("element_id") or "")
        if not found:
            continue                       # hallucinated id
        face, el = found
        target = {"kind": "element", "id": el["id"], "face": face}
        if op.get("op") == "delete":
            out.append({"target": target, "remove": True})
            continue
        patch = _patch_for(op, el)
        if patch:
            out.append({"target": target, "patch": patch})
    return out
