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
    """Non-superseded checkpoint rows for a session, oldest first.

    Fault-tolerant on purpose, exactly like `capture` and `relabel`. This is on
    the hot path of EVERY v2 canvas turn (~7 call sites in `orchestrator_v2`,
    all unwrapped), and `postgrest` raises `APIError` on any non-2xx — so a
    database that has not had `20260801000001_session_checkpoints.sql` applied
    yet answers `PGRST205` (table missing) and would 500 the whole conversation
    rather than just the Back menu.

    Returning [] degrades to "no Back destinations offered", which is precisely
    what the feature already uses to mean "no going back" — there is no separate
    disable flag to keep in sync. That is what makes the code genuinely
    deploy-order-independent: ship it before the migration and the customer sees
    no Back button, not a broken chat.
    """
    try:
        res = (sb.table("session_checkpoints")
               .select("seq, kind, label, step_id")
               .eq("session_id", session_id)
               .is_("superseded_at", "null")
               .order("seq")
               .execute())
        return list(res.data or [])
    except Exception as exc:                     # noqa: BLE001 — best effort
        # No row content in the log: labels carry the customer's own name
        # (security rule 10). The exception TYPE is enough to tell a missing
        # table from a transport error.
        log.warning("checkpoint_live_rows_failed", error=type(exc).__name__)
        return []


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
               .select("seq, step_id, superseded_at").eq("session_id", session_id)
               .order("seq").execute())
        rows = list(res.data or [])
        seq = max((r["seq"] for r in rows), default=0) + 1
        if _is_a_re_entry_not_a_new_pass(rows, step, previous_state):
            return
        sb.table("session_checkpoints").insert({
            "session_id": session_id,
            "seq": seq,
            "kind": cpt.kind,
            "label": cpt.label(collected),
            "step_id": step.id.value,
            "collected": collected,
            "canvas_design": (canvas_design if canvas_design is not None
                              else _last_known_canvas(sb, session_id)),
            "chat_watermark": _last_chat_id(sb, session_id),
        }).execute()
    except Exception:                        # noqa: BLE001 — best effort
        log.warning("checkpoint_capture_failed", step=step.id.value)


def _is_a_re_entry_not_a_new_pass(rows: list[dict], step: cs.Step,
                                  previous_state) -> bool:
    """True when this opener already has a LIVE row and we did NOT get here by
    closing the previous pass — i.e. the router walked BACKWARD into a group the
    customer never left, so a second row would be a confusing duplicate.

    The one legitimate repeat is a loop pass, and every loop pass is reached
    through a `closes_checkpoint` step (`ASK_ANOTHER_LOGO` / `ASK_ANYTHING_ELSE`
    — the steps whose apply banks or clears the group's state). Cancelling a mix
    at `ASK_DECORATION_MIX` re-opens `ASK_DECORATION` without passing through
    one, and wrote a duplicate `Decoration — not set` row.
    """
    live = [r for r in rows if r.get("superseded_at") is None]
    if not live:
        return False
    newest = max(live, key=lambda r: r["seq"])
    if newest.get("step_id") != step.id.value:
        return False
    prev = cs.by_id_value(getattr(previous_state, "value", previous_state))
    return not (prev is not None and prev.closes_checkpoint)


def _last_known_canvas(sb, session_id: str) -> dict:
    """The newest live snapshot's canvas, for a capture with no live blob.

    Not every capture is driven by a customer turn: `check_verification` is a
    poll and carries no canvas. Storing None there is the "unknown" state that
    left a restore with no honest move — skipping the canvas restore orphans
    elements on the cap (locked and unselectable, and flattened into the render),
    while clearing it would wipe a design the customer really had. Carrying the
    last OBSERVED canvas forward removes the ambiguity: a snapshot is always
    either what was on screen or the most recent thing that was.

    `{}` when nothing has ever been observed — which is only true before the
    first turn, where the canvas genuinely is empty.
    """
    try:
        res = (sb.table("session_checkpoints")
               .select("seq, canvas_design").eq("session_id", session_id)
               .is_("superseded_at", "null").execute())
        rows = [r for r in (res.data or []) if r.get("canvas_design") is not None]
        if not rows:
            return {}
        return max(rows, key=lambda r: r["seq"])["canvas_design"]
    except Exception as exc:                     # noqa: BLE001 — best effort
        log.warning("checkpoint_last_canvas_failed", error=type(exc).__name__)
        return {}


def relabel(sb, session_id: str, collected: dict) -> None:
    """Re-render the newest live checkpoint's label against the CURRENT collected.

    Labels are rendered at capture time, which is by definition BEFORE the step
    that opens the checkpoint has been answered — so a freshly captured row
    always carries its "unanswered" fallback ("Your name — not set"). This runs
    after each answered turn and rewrites the newest live row, which is the
    checkpoint currently in progress, so the menu shows the customer's own
    answer back to them.

    `collected` is what the CALLER decides it is, and that matters: for a
    `closes_checkpoint` step `orchestrator_v2` passes the pre-apply snapshot, so
    the row keeps the identity of the pass being left rather than the next one's.

    Newest-live is the right anchor: a new group's capture writes a new row that
    immediately becomes newest, so each group's label stops updating exactly when
    the customer moves past it — which is what pins a loop pass's label to ITS
    pass ("Logo 1 — front" stays put once "Logo 2" is captured).

    Best-effort, like capture: a label is a convenience and must never break a turn.
    """
    row = None
    try:
        rows = live_rows(sb, session_id)
        if not rows:
            return
        row = rows[-1]                       # live_rows orders by seq ascending
        step = cs.by_id_value(row["step_id"])
        if step is None or step.checkpoint is None:
            return
        new_label = step.checkpoint.label(collected)
        if new_label == row.get("label"):
            return
        # Verb FIRST, filters after — see the note in `restore` above.
        (sb.table("session_checkpoints").update({"label": new_label})
         .eq("session_id", session_id).eq("seq", row["seq"]).execute())
    except Exception:                        # noqa: BLE001 — best effort
        # Never log the rendered label itself — it can carry the customer's
        # name (security rule 10). seq/step_id are safe, opaque identifiers.
        log.warning("checkpoint_relabel_failed",
                    seq=row.get("seq") if row else None,
                    step_id=row.get("step_id") if row else None)


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
