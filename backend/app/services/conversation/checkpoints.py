"""Snapshot-and-restore for the v2 canvas Back menu.

All checkpoint DB work lives here so `orchestrator_v2` stays a router. The
routing decisions (which checkpoints exist, which are offerable) are pure and
live in `canvas_steps` / `state_machine_v2`; this module only reads and writes.

Rows are append-only. A restore marks later rows `superseded_at` and never
deletes, so a discarded branch stays reconstructable for audit.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.services.conversation import canvas_steps as cs

log = structlog.get_logger(__name__)

# Values written OUTSIDE the step that a snapshot predates, which a restore must
# NOT roll back. `email_verified` is the load-bearing one: it is written out of
# band by `leads._mark_session_verified` when the customer clicks the emailed
# link, which can land at any point after a snapshot was taken. A plain
# replacement would un-verify a verified customer and re-ask for their address.
#
# ONE constant, deliberately: a key added to the commit set later and missed
# here is silent data loss with no failing test to catch it.
CARRY_FORWARD_KEYS: frozenset[str] = frozenset({
    "email_captured", "email_verified", "lead_id",
    "quote_requested", "reference_code",
})


class CheckpointUnavailable(Exception):
    """The requested seq is unknown, already superseded, or frozen."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def live_rows(sb, session_id: str) -> list[dict]:
    """Non-superseded checkpoint rows for a session, oldest first."""
    res = (sb.table("session_checkpoints")
           .select("seq, kind, label, step_id")
           .eq("session_id", session_id)
           .is_("superseded_at", "null")
           .order("seq")
           .execute())
    return list(res.data or [])


def capture(sb, session_id: str, step: cs.Step, previous_state,
            collected: dict, canvas_design: dict | None) -> None:
    """Snapshot the session on ENTRY to a checkpoint-opening step.

    Correct by construction: the turn that carries the session INTO Logo 2
    carries `collected` and the canvas as they stood at the END of Logo 1.
    Nothing is derived.

    Keyed on the TRANSITION — `previous_state is not step.id` — rather than on
    a loop index read from `collected`. Two reasons, and the second is the
    load-bearing one:

    1. It is idempotent for free. A stall, a retry, a blank turn and an abuse
       decline all re-render the CURRENT step, so previous == step and nothing
       is written.
    2. The decor loop banks NO collection to index. `_apply_anything_else`
       pops decor_choice/decor_face/decor_placed on every "Add something else",
       so a `len(collected["decor"])` key would read 0 on every pass, collide,
       and silently capture only the first decoration. The logo loop does bank
       `logos`, but keying the two differently would be two rules to keep in
       step. Re-entering an opener from elsewhere in the loop is unambiguously
       a new pass for both.

    Best-effort: a checkpoint is a convenience, and failing to write one must
    never break the customer's turn.
    """
    if step.checkpoint is None or previous_state is step.id:
        return
    cpt = step.checkpoint
    try:
        # Max over ALL rows, superseded included — `seq` is monotonic for the
        # life of the session. Counting only live rows would reissue a seq a
        # restore had just superseded, violating the (session_id, seq) unique
        # index and 500-ing the turn.
        res = (sb.table("session_checkpoints")
               .select("seq").eq("session_id", session_id)
               .order("seq").execute())
        rows = list(res.data or [])
        seq = max((r["seq"] for r in rows), default=0) + 1
        watermark = _last_chat_id(sb, session_id)
        sb.table("session_checkpoints").insert({
            "session_id": session_id,
            "seq": seq,
            "kind": cpt.kind,
            "label": cpt.label(collected),
            "step_id": step.id.value,
            "collected": collected,
            "canvas_design": canvas_design,
            "chat_watermark": watermark,
        }).execute()
    except Exception:                        # noqa: BLE001 — best effort
        log.warning("checkpoint_capture_failed", step=step.id.value)


def _last_chat_id(sb, session_id: str) -> str | None:
    res = (sb.table("chat_messages").select("id")
           .eq("session_id", session_id)
           .order("created_at", desc=True).limit(1).execute())
    rows = list(res.data or [])
    return rows[0]["id"] if rows else None


def restore(sb, session_id: str, seq: int, live_collected: dict) -> dict | None:
    """Roll the session back to checkpoint `seq`.

    Returns the checkpoint row (with `collected` already carry-forward-merged),
    or None if the seq is unknown or already superseded — which is the
    double-tap / stale-tab case the route turns into a 409.

    NOT best-effort: unlike capture, a half-done restore would leave the session
    inconsistent, so failures propagate.
    """
    res = (sb.table("session_checkpoints")
           .select("seq, kind, label, step_id, collected, canvas_design, "
                   "chat_watermark, superseded_at")
           .eq("session_id", session_id).eq("seq", seq).limit(1).execute())
    rows = list(res.data or [])
    if not rows or rows[0].get("superseded_at"):
        return None
    row = dict(rows[0])

    restored = dict(row.get("collected") or {})
    for key in CARRY_FORWARD_KEYS:
        if key in live_collected:
            restored[key] = live_collected[key]
    row["collected"] = restored

    stamp = _now()
    # Verb FIRST, filters after: `sb.table(...)` returns postgrest's
    # `SyncRequestBuilder`, which has no filter methods at all — `.eq`/`.gt`
    # only exist on the `SyncFilterRequestBuilder` returned by `.update()`/
    # `.select()`/etc. Every other call site in `app/` (e.g.
    # `app/api/routes/leads.py`) follows this order; do not "simplify" it to
    # filters-first, which raises `AttributeError` against the real client.
    (sb.table("session_checkpoints").update({"superseded_at": stamp})
     .eq("session_id", session_id).gt("seq", seq).execute())
    watermark = row.get("chat_watermark")
    chat = sb.table("chat_messages").update({"superseded_at": stamp}).eq(
        "session_id", session_id)
    if watermark:
        # Rows written after the snapshot's last message. `id` is a uuid, so
        # ordering is by created_at via the watermark row's timestamp.
        chat = chat.gt("created_at", _created_at_of(sb, watermark))
    chat.execute()
    log.info("checkpoint_restored", seq=seq, kind=row.get("kind"))
    return row


def _created_at_of(sb, message_id: str) -> str:
    res = (sb.table("chat_messages").select("created_at")
           .eq("id", message_id).limit(1).execute())
    rows = list(res.data or [])
    return rows[0]["created_at"] if rows else "1970-01-01T00:00:00Z"
