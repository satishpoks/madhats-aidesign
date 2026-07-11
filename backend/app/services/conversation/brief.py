"""Accumulate structured design elements into one canonical brief.

The brief is the single source of design intent for both flows (uploaded logo
and described design) and for post-generation refinement. Merging is additive
and lossless: lists grow (de-duplicated), scalars fill once, and a freeform
element that arrives as a bare ``summary`` when we already have one is kept as a
text element rather than dropped (the no-LLM path produces summary-only dicts).
"""
from __future__ import annotations

_LIST_KEYS = ("text_elements", "colours", "imagery")
_SCALAR_KEYS = ("summary", "style")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def merge_brief(existing: dict | None, incoming: dict | None) -> dict:
    existing = existing or {}
    incoming = incoming or {}
    out: dict = {}

    for key in _LIST_KEYS:
        out[key] = _dedupe(list(existing.get(key) or []) + list(incoming.get(key) or []))

    for key in _SCALAR_KEYS:
        out[key] = (existing.get(key) or incoming.get(key) or "").strip()

    inc_summary = (incoming.get(key := "summary") and incoming[key].strip()) or ""
    has_incoming_lists = any(incoming.get(k) for k in _LIST_KEYS)
    if inc_summary and existing.get("summary") and not has_incoming_lists:
        if inc_summary not in out["text_elements"]:
            out["text_elements"].append(inc_summary)

    # Prune empties so the prompt builder never emits dangling labels.
    return {k: v for k, v in out.items() if v}
