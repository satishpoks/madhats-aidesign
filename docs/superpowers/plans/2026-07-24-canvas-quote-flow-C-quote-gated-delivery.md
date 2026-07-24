# Workstream C — Quote-Gated Delivery + Generation Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the customer-facing AI-render + design-email flow with a quote-gated one — an explicit "Request a quote" step mints a tracking reference, the customer is emailed only that reference after verifying, sales is notified once (summary + all uploaded components), the photoreal render is produced on-demand from the admin, and the multi-angle generation bug (front-aliased back/side faces + missing overlap order) is fixed.

**Architecture:** A new v2 registry step (`REQUEST_QUOTE`) records the request on the `leads` row (new `reference_code` + `quote_requested` columns) and converges with the async email-verification track through a new idempotent `delivery.maybe_send_quote_confirmation` primitive that sends the customer reference email + the sales notification (with components attached). Canvas finalize no longer triggers generation for this flow; `maybe_send_preview`/`send_final_design` refuse to email the design for quote-gated sessions; a new `POST /admin/quote-requests/{lead_id}/render` triggers the existing `_run_generation` canvas pipeline (now carrying the C6 fix: `_map_views` stops fabricating angle aliases, the render loop skips non-front faces lacking a genuine angle, and per-face prompts carry explicit front-to-back z-order). The admin quote-requests view surfaces the reference, summary, downloadable components, and the render button/result.

**Tech Stack:** Python 3.12, FastAPI, Supabase (supabase-py), pytest; React admin frontend

## Global Constraints
- The system NEVER emails the design to the customer in this batch (send-quote is out of scope). Customer post-verification email carries the reference only.
- No secrets in code; admin routes gated by X-Admin-Secret (+ X-Store-Key for store-scoped).
- No PII in logs. SQL migrations only (no Alembic). supabase-py service-role client.
- Reuse per-store `sales_notification_email`; do NOT add a new notify field.
- Baseline `CANVAS_ORCHESTRATOR_V2=false pytest -q` stays green.

---

## File Structure

```
backend/
  supabase/migrations/
    20260724000001_leads_reference_code.sql        (Create — Task 1)
    20260724000002_generation_render_notes.sql     (Create — Task 10)
  app/
    services/
      leads.py                    (Modify — Tasks 1,2: ref-code generator + record_quote_request)
      delivery.py                 (Modify — Tasks 4,7: quote-gate guards + maybe_send_quote_confirmation)
      email.py                    (Modify — Task 6: send_quote_reference_email + send_quote_request_to_sales)
      components.py               (Create — Task 5: enumerate_components)
      catalogue_sync.py           (Modify — Task 9: _map_views stops fabricating aliases)
      prompt_builder.py           (Modify — Task 11: z-order injection + genuine-angle helper)
      conversation/
        canvas_steps.py           (Modify — Task 3: REQUEST_QUOTE Step + apply)
        state_machine_v2.py       (Modify — Task 3: progress anchor)
        state_machine.py          (Modify — Task 3: REQUEST_QUOTE enum member)
    api/routes/
      sessions.py                 (Modify — Task 3: finalize_canvas v2 branch stops generating)
      leads.py                    (Modify — Task 7: trigger maybe_send_quote_confirmation)
      generate.py                 (Modify — Tasks 8,10: skip non-front faces + render_notes + enqueue_render)
      admin_leads.py              (Modify — Task 12: list fields + components + render endpoint)
    prompts.py                    (Modify — Task 6: quote-reference + sales-request email templates)
  tests/
    test_leads_reference_code.py  (Create — Tasks 1,2)
    test_request_quote_step.py    (Create — Task 3)
    test_delivery_quote_gate.py   (Create — Tasks 4,7)
    test_components.py            (Create — Task 5)
    test_quote_emails.py          (Create — Task 6)
    test_admin_quote_render.py    (Create — Tasks 8,12)
    test_catalogue_sync_views.py  (Create — Task 9)
    test_canvas_generation.py     (Modify — Task 10: skip-face behaviour)
    test_prompt_builder.py        (Modify — Task 11: z-order injection)
frontend/src/admin/
  adminApi.ts                     (Modify — Task 13)
  views/QuoteRequestsView.tsx     (Modify — Task 13)
  views/QuoteRequestsView.test.tsx (Create — Task 13)
```

---

### Task 1: Migration + tracking-reference generator

Adds the `reference_code` and quote-request columns to `leads`, and the collision-checked `MH-XXXXXX` generator + assignment helper in `leads.py`.

**Files:**
- Create: `backend/supabase/migrations/20260724000001_leads_reference_code.sql`
- Modify: `backend/app/services/leads.py` (add generator + `assign_reference_code` after `hash_token` ~line 39)
- Test: `backend/tests/test_leads_reference_code.py` (Create)

**Interfaces:**
- Produces: `leads.generate_reference_code() -> str`, `leads.assign_reference_code(sb, lead_id: str) -> str`
- Consumes: `app.db.get_supabase` (passed in as `sb`)

- [ ] **Step 1:** Write the failing test. Create `backend/tests/test_leads_reference_code.py`:
```python
"""MH-XXXXXX tracking reference generation + collision-checked assignment."""
from __future__ import annotations

import re

from app.services import leads as leads_service


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, rows, sink):
        self._table, self._rows, self._sink = table, rows, sink
        self._pending_update = None

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def execute(self):
        if self._pending_update is not None:
            self._sink.append(self._pending_update)
            for row in self._rows:
                row.update(self._pending_update)
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, rows):
        self._rows = rows
        self.sink: list = []

    def table(self, name):
        return _Query(name, self._rows, self.sink)


def test_generate_reference_code_shape():
    for _ in range(200):
        code = leads_service.generate_reference_code()
        assert re.fullmatch(r"MH-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}", code), code
        # ambiguous glyphs never appear
        assert not (set("O0I1") & set(code[3:]))


def test_assign_reference_code_avoids_collision(monkeypatch):
    fake = _FakeSB([{"id": "lead-1", "reference_code": None},
                    {"id": "other", "reference_code": "MH-AAAAAA"}])
    # First candidate collides with the existing row; second is free.
    seq = iter(["MH-AAAAAA", "MH-BCDFGH"])
    monkeypatch.setattr(leads_service, "generate_reference_code", lambda: next(seq))
    code = leads_service.assign_reference_code(fake, "lead-1")
    assert code == "MH-BCDFGH"
    assert fake.sink == [{"reference_code": "MH-BCDFGH"}]
```

- [ ] **Step 2:** Run it — expect FAIL (AttributeError: module has no `generate_reference_code`).
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_leads_reference_code.py -v
```

- [ ] **Step 3:** Write the migration `backend/supabase/migrations/20260724000001_leads_reference_code.sql`:
```sql
-- Quote-gated delivery (Workstream C). The customer explicitly requests a quote;
-- we mint a customer-facing tracking reference (MH-XXXXXX), stop emailing the
-- design, and email only the reference after verification. reference_code is the
-- request identity (unique). quote_requested marks the explicit submit gesture;
-- quote_confirmation_sent dedups the one-time customer-reference + sales emails.
alter table leads add column if not exists reference_code          text;
alter table leads add column if not exists quote_requested         bool not null default false;
alter table leads add column if not exists quote_requested_at      timestamptz;
alter table leads add column if not exists quote_confirmation_sent bool not null default false;

create unique index if not exists idx_leads_reference_code
  on leads(reference_code) where reference_code is not null;
```

- [ ] **Step 4:** Implement the generator + assignment in `backend/app/services/leads.py`. Add `import secrets` to the imports (top of file, alphabetically near `import re`), then insert after `hash_token` (~line 39):
```python
# Base32 alphabet with the ambiguous glyphs 0/O/1/I removed (24 letters + 8
# digits = 32 symbols). Customer-facing, so readability over a phone matters.
_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_reference_code() -> str:
    """A short customer-facing tracking reference, e.g. ``MH-7F3K2A``."""
    return "MH-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(6))


def assign_reference_code(sb, lead_id: str) -> str:
    """Allocate a unique reference code and persist it on the lead row.

    Collision-checked against ``leads.reference_code`` (unique-indexed). Retries
    a bounded number of times before giving up — with a 32^6 space a collision is
    astronomically unlikely, so 10 attempts is ample headroom.
    """
    for _ in range(10):
        code = generate_reference_code()
        existing = (
            sb.table("leads").select("id").eq("reference_code", code).limit(1).execute()
        )
        if not existing.data:
            sb.table("leads").update({"reference_code": code}).eq("id", lead_id).execute()
            return code
    raise RuntimeError("could not allocate a unique reference code")
```

- [ ] **Step 5:** Run it — expect PASS.
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_leads_reference_code.py -v
```

- [ ] **Step 6:** Commit.
```bash
cd backend && git add app/services/leads.py supabase/migrations/20260724000001_leads_reference_code.sql tests/test_leads_reference_code.py && git commit -m "feat(quote): leads.reference_code column + MH-XXXXXX generator (C2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `record_quote_request` — the request-recording primitive

Marks the lead `quote_requested`, allocates the reference, and best-effort converges with an already-verified email track. Called by the C1 step's apply hook.

**Files:**
- Modify: `backend/app/services/leads.py` (add `record_quote_request` after `assign_reference_code`)
- Test: `backend/tests/test_leads_reference_code.py` (add cases)

**Interfaces:**
- Produces: `leads.record_quote_request(session: dict, collected: dict) -> str | None`
- Consumes: `leads.assign_reference_code`, `delivery.maybe_send_quote_confirmation` (Task 7; imported lazily so ordering is tolerant)

- [ ] **Step 1:** Add the failing test to `backend/tests/test_leads_reference_code.py`:
```python
def test_record_quote_request_marks_lead_and_returns_code(monkeypatch):
    rows = [{"id": "lead-1", "session_id": "sess-1", "reference_code": None,
             "created_at": "2026-07-24T00:00:00Z"}]
    fake = _FakeSB(rows)
    monkeypatch.setattr(leads_service, "get_supabase", lambda: fake)
    monkeypatch.setattr(leads_service, "generate_reference_code", lambda: "MH-BCDFGH")
    # Converge call is best-effort; stub it so this test stays about recording.
    calls = []
    import app.services.delivery as delivery
    monkeypatch.setattr(delivery, "maybe_send_quote_confirmation", lambda sid: calls.append(sid))

    code = leads_service.record_quote_request({"id": "sess-1"}, {})
    assert code == "MH-BCDFGH"
    assert rows[0]["reference_code"] == "MH-BCDFGH"
    assert rows[0]["quote_requested"] is True
    assert rows[0]["quote_requested_at"]
    assert calls == ["sess-1"]


def test_record_quote_request_no_lead_returns_none(monkeypatch):
    fake = _FakeSB([])
    monkeypatch.setattr(leads_service, "get_supabase", lambda: fake)
    assert leads_service.record_quote_request({"id": "missing"}, {}) is None
```

- [ ] **Step 2:** Run it — expect FAIL (no `record_quote_request`).
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_leads_reference_code.py -k record_quote_request -v
```

- [ ] **Step 3:** Implement `record_quote_request` in `backend/app/services/leads.py`, immediately after `assign_reference_code`:
```python
def _latest_lead(sb, session_id: str) -> dict | None:
    res = (
        sb.table("leads")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def record_quote_request(session: dict, collected: dict) -> str | None:
    """Record an explicit customer quote request against the session's lead.

    Sets ``quote_requested`` (+ timestamp), allocates a reference code (idempotent
    — an existing code is reused), and best-effort converges with the async
    email-verification track: if the email is already verified the customer
    reference email + sales notification fire now; otherwise they fire when
    verification completes (see delivery.maybe_send_quote_confirmation). Returns
    the reference code, or None when no lead exists yet.

    PII-safe: session_id / lead_id only in logs.
    """
    sb = get_supabase()
    session_id = session["id"]
    lead = _latest_lead(sb, session_id)
    if not lead:
        log.warning("record_quote_request_no_lead", session_id=session_id)
        return None

    code = lead.get("reference_code") or assign_reference_code(sb, lead["id"])
    sb.table("leads").update(
        {
            "quote_requested": True,
            "quote_requested_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", lead["id"]).execute()
    log.info("quote_requested", session_id=session_id, lead_id=lead["id"])  # no PII

    try:
        from app.services import delivery  # noqa: PLC0415 — avoid import cycle

        delivery.maybe_send_quote_confirmation(session_id)
    except Exception as exc:  # noqa: BLE001 — never fail the request over a side effect
        log.error("quote_converge_failed", session_id=session_id, error_type=type(exc).__name__)
    return code
```

- [ ] **Step 4:** Run it — expect PASS. (`maybe_send_quote_confirmation` is monkeypatched in Task 2's tests; the lazy import means the real one lands in Task 7.)
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_leads_reference_code.py -v
```

- [ ] **Step 5:** Commit.
```bash
cd backend && git add app/services/leads.py tests/test_leads_reference_code.py && git commit -m "feat(quote): record_quote_request records + converges the request (C1/C2/C3)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: C1 — explicit "Request a quote" step + finalize stops generating

Adds a `REQUEST_QUOTE` registry step (between `ASK_PURPOSE` and `FINALIZE_CANVAS`) whose "Request a quote" chip records the request, and makes the v2 `canvas-finalize` route stop triggering generation — returning the reference on-screen instead.

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py` (add `REQUEST_QUOTE` enum member after `FINALIZE_CANVAS` ~line 49)
- Modify: `backend/app/services/conversation/canvas_steps.py` (add `_apply_request_quote` + Step, before `FINALIZE_CANVAS` ~line 583)
- Modify: `backend/app/services/conversation/state_machine_v2.py` (progress anchor ~line 63)
- Modify: `backend/app/api/routes/sessions.py` (v2 `finalize_canvas` branch ~line 268)
- Test: `backend/tests/test_request_quote_step.py` (Create)

**Interfaces:**
- Produces: `ConversationState.REQUEST_QUOTE`; a `Step(id=S.REQUEST_QUOTE, ...)` in `canvas_steps.REGISTRY`
- Consumes: `leads.record_quote_request`

- [ ] **Step 1:** Write the failing test. Create `backend/tests/test_request_quote_step.py`:
```python
"""C1 — the REQUEST_QUOTE registry step records the request via its apply hook."""
from __future__ import annotations

from app.services.conversation import canvas_steps as cs
from app.services.conversation import state_machine_v2 as sm2
from app.services.conversation.state_machine import ConversationState as S


def _step(state):
    return cs.by_id(state)


def test_request_quote_step_exists_between_purpose_and_finalize():
    ids = [s.id for s in cs.REGISTRY]
    assert S.REQUEST_QUOTE in ids
    assert ids.index(S.ASK_PURPOSE) < ids.index(S.REQUEST_QUOTE) < ids.index(S.FINALIZE_CANVAS)


def test_request_quote_chip_records_and_stores_reference(monkeypatch):
    step = _step(S.REQUEST_QUOTE)
    fields = sm2.resolve_chip(step, "Request a quote", {})
    assert fields == {"quote_requested": True}

    calls = {}
    def _record(session, collected):
        calls["session"] = session
        return "MH-BCDFGH"
    from app.services import leads as leads_service
    monkeypatch.setattr(leads_service, "record_quote_request", _record)

    collected: dict = {}
    step.apply(collected, fields, {"id": "sess-1"})
    assert collected["quote_requested"] is True
    assert collected["reference_code"] == "MH-BCDFGH"
    assert calls["session"] == {"id": "sess-1"}


def test_request_quote_gates_finalize_until_requested():
    # With everything before it satisfied but no quote_requested, first-unmet
    # rests on REQUEST_QUOTE — never FINALIZE_CANVAS. (needed_by is included so
    # this stays correct once Workstream B's needed_by step is merged before
    # purpose — an unused key is harmless if that step isn't present yet.)
    done = {"name": "Ann", "intro_ack": True, "logos_done": True, "decor_done": True,
            "quantity": 1, "decoration_done": True, "email_captured": True,
            "needed_by": "ASAP", "purpose": "team"}
    assert sm2.next_step(done).id is S.REQUEST_QUOTE
    done["quote_requested"] = True
    assert sm2.next_step(done).id is S.FINALIZE_CANVAS
```

- [ ] **Step 2:** Run it — expect FAIL (`AttributeError: REQUEST_QUOTE`).
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_request_quote_step.py -v
```

- [ ] **Step 3:** Add the enum member in `backend/app/services/conversation/state_machine.py`, immediately after `FINALIZE_CANVAS = "finalize_canvas"` (~line 49):
```python
    REQUEST_QUOTE = "request_quote"   # v2 quote-gated: explicit submit before finalize
```

- [ ] **Step 4:** Add the apply hook + Step in `backend/app/services/conversation/canvas_steps.py`. Insert `_apply_request_quote` after `_apply_decoration_mix` (~line 327):
```python
def _apply_request_quote(c: dict, f: dict, s: dict) -> None:
    """Record the explicit quote request and stash the reference for on-screen.

    The lead already exists (email was captured at ASK_EMAIL). Recording mints
    the tracking reference, marks the lead, and best-effort converges with the
    verification track. `quote_requested` on `collected` is what satisfies
    done_when; `reference_code` is surfaced to the customer immediately.
    """
    if not f.get("quote_requested"):
        return
    code = leads_service.record_quote_request(s, c)
    if code:
        c["reference_code"] = code
    c["quote_requested"] = True
```
Then insert the Step into `REGISTRY` immediately BEFORE the `FINALIZE_CANVAS` step (~line 583):
```python
    Step(
        id=S.REQUEST_QUOTE,
        ask=("Your design's ready to go, {name}! Tap below to send it to our "
             "team — they'll put together a quote and get back to you."),
        chips=(Chip("Request a quote", {"quote_requested": True}),),
        slots=("quote_requested",),
        apply=_apply_request_quote,
        done_when=lambda c: bool(c.get("quote_requested")),
    ),
```

- [ ] **Step 5:** Add the progress anchor so the step reads as final (no counter growth). In `backend/app/services/conversation/state_machine_v2.py`, add to `_PROGRESS_ANCHORS` (~line 63), after the `ASK_DECORATION_MIX` entry:
```python
    # The explicit submit is the last beat of ASK_PURPOSE, not a numbered step.
    S.REQUEST_QUOTE: S.ASK_PURPOSE,
```

- [ ] **Step 6:** Make the v2 finalize stop generating. In `backend/app/api/routes/sessions.py`, replace the `if settings.canvas_orchestrator_v2:` block inside `finalize_canvas` (~lines 268–280) with:
```python
    # v2 step-by-step orchestrator: the design phase already happened in chat and
    # the customer explicitly requested a quote (REQUEST_QUOTE) before this. This
    # is a QUOTE-GATED flow: we do NOT AI-render or email the design to the
    # customer. Persist the canvas so the render can be produced on-demand from
    # the admin later (C4), surface the tracking reference on-screen, and end the
    # customer journey at the reference confirmation. Sales is notified + the
    # customer emailed the reference via the verification-track converge (C2/C3).
    if settings.canvas_orchestrator_v2:
        from app.services.conversation.state_machine_v2 import progress_v2

        reference = collected.get("reference_code")
        new_state = S.QUOTE_REQUESTED
        if reference:
            reply = (
                f"All done — your request is in! Your reference is {reference}. "
                "Our team will be in touch with a quote soon. We've also emailed "
                "it to you once you confirm your address."
            )
        else:
            reply = (
                "All done — your request is in! Our team will be in touch with a "
                "quote soon."
            )
        sb.table("design_sessions").update(
            {"canvas_design": body.canvas_design, "collected": collected, "state": new_state.value}
        ).eq("id", session_id).execute()
        return {
            "reply": reply,
            "state": new_state.value,
            "data": {"reference_code": reference, "progress": progress_v2(new_state, collected)},
        }
```

- [ ] **Step 7:** Run the step test + the v2 e2e + state-machine suites — expect PASS.
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_request_quote_step.py tests/test_state_machine_v2.py tests/test_v2_e2e.py -v
```

- [ ] **Step 8:** Commit.
```bash
cd backend && git add app/services/conversation/state_machine.py app/services/conversation/canvas_steps.py app/services/conversation/state_machine_v2.py app/api/routes/sessions.py tests/test_request_quote_step.py && git commit -m "feat(quote): explicit Request-a-quote step; finalize stops generating (C1/C4)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Stop emailing the design for quote-gated sessions

Guards `maybe_send_preview` and `send_final_design` to refuse the customer design email whenever the session is quote-gated (`collected["quote_requested"]`) — so even an on-demand admin render (C4) or a backfill sweep can never leak the design to the customer.

**Files:**
- Modify: `backend/app/services/delivery.py` (`maybe_send_preview` guard at top ~line 112; `send_final_design` guard ~line 342)
- Test: `backend/tests/test_delivery_quote_gate.py` (Create)

**Interfaces:**
- Consumes: `design_sessions.collected["quote_requested"]`
- Produces: (behaviour) `maybe_send_preview` / `send_final_design` return `False` early for quote-gated sessions

- [ ] **Step 1:** Write the failing test. Create `backend/tests/test_delivery_quote_gate.py` (reuse the `_Query`/`_FakeSB` shape from `test_delivery.py`):
```python
"""Quote-gated sessions never receive the design by email (C2)."""
from __future__ import annotations

from app.services import delivery


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, rows, sink):
        self._table, self._rows, self._sink = table, rows, sink
        self._pending_update = None

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def order(self, field, desc=False, **k):
        self._rows = sorted(self._rows, key=lambda r: r.get(field) or "", reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def execute(self):
        if self._pending_update is not None:
            self._sink.append((self._table, self._pending_update))
            for row in self._rows:
                row.update(self._pending_update)
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, tables):
        self._tables = tables
        self.sink: list = []

    def table(self, name):
        return _Query(name, list(self._tables.get(name, [])), self.sink)


def test_maybe_send_preview_skips_quote_gated(monkeypatch):
    sent = []
    from app.services import email as email_service
    monkeypatch.setattr(email_service, "send_preview_email", lambda *a, **k: sent.append(a))
    fake = _FakeSB({
        "design_sessions": [{"id": "sess-1", "collected": {"quote_requested": True}}],
        "leads": [{"id": "lead-1", "session_id": "sess-1", "email_verified": True,
                   "preview_email_sent": False, "email": "a@b.com", "name": "Ann",
                   "created_at": "2026-07-24T00:00:00Z"}],
        "generations": [{"id": "g", "session_id": "sess-1", "status": "complete",
                         "image_url": "generations/clean.png", "created_at": "2026-07-24T00:00:00Z"}],
    })
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)
    assert delivery.maybe_send_preview("sess-1") is False
    assert sent == []


def test_send_final_design_skips_quote_gated(monkeypatch):
    fake = _FakeSB({"design_sessions": [{"id": "sess-1", "collected": {"quote_requested": True}}]})
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)
    # Two completed gens would normally qualify; the guard short-circuits first.
    monkeypatch.setattr(delivery, "_completed_generations",
                        lambda sid: [{"image_url": "a"}, {"image_url": "b"}])
    assert delivery.send_final_design("sess-1") is False
```

- [ ] **Step 2:** Run it — expect FAIL (the guard doesn't exist; preview/final would proceed).
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_delivery_quote_gate.py -v
```

- [ ] **Step 3:** Add a shared helper + guards in `backend/app/services/delivery.py`. Insert the helper after `_fetch_image_bytes` (~line 94):
```python
def _is_quote_gated(sb, session_id: str) -> bool:
    """True when the session is the quote-gated canvas flow.

    For these sessions the customer NEVER receives the design by email — they get
    a tracking reference only (C2). Delivery of the design to the customer is
    fully out of scope this batch, so both the preview and the final-design sends
    are refused here regardless of generation state.
    """
    row = (
        sb.table("design_sessions").select("collected").eq("id", session_id).limit(1).execute()
    )
    if not row.data:
        return False
    return bool((row.data[0].get("collected") or {}).get("quote_requested"))
```
Add the guard at the very top of `maybe_send_preview`, immediately after `sb = get_supabase()` (~line 112):
```python
    if _is_quote_gated(sb, session_id):
        # Quote-gated flow: the customer gets a reference, never the design.
        return False
```
Add the guard at the top of `send_final_design`, immediately after the docstring (~line 342), before `gens = _completed_generations(...)`:
```python
    if _is_quote_gated(get_supabase(), session_id):
        return False
```

- [ ] **Step 4:** Run it — expect PASS. Also re-run the existing delivery suite to confirm non-quote flows still send.
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_delivery_quote_gate.py tests/test_delivery.py -v
```

- [ ] **Step 5:** Commit.
```bash
cd backend && git add app/services/delivery.py tests/test_delivery_quote_gate.py && git commit -m "feat(quote): never email the design for quote-gated sessions (C2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: C5 — component enumeration

A pure enumerator of every uploaded/derived component path for a session, used by the sales email (Task 7) and the admin view (Task 12).

**Files:**
- Create: `backend/app/services/components.py`
- Test: `backend/tests/test_components.py` (Create)

**Interfaces:**
- Produces: `components.enumerate_components(collected: dict, generation: dict | None = None) -> list[dict]` → each `{"label": str, "path": str}` (storage paths only)
- Consumes: `collected["uploaded_asset_path"|"canvas_previews"|"canvas_layouts"|"elements"]`, `generation["view_images"]`

- [ ] **Step 1:** Write the failing test. Create `backend/tests/test_components.py`:
```python
"""Enumerate the uploaded/derived component set for a quote request (C5)."""
from __future__ import annotations

from app.services import components


def test_enumerate_components_covers_every_source():
    collected = {
        "uploaded_asset_path": "uploads/logo.png",
        "canvas_previews": {"front": "composite/f.png", "back": "composite/b.png"},
        "canvas_layouts": {"front": "uploads/lay_f.png"},
        "elements": [
            {"type": "logo", "asset_path": "uploads/el1.png"},
            {"type": "text", "content": "hi"},                       # no path — skipped
            {"type": "logo", "assetUrl": "https://cdn/x.png"},       # external — skipped
        ],
    }
    gen = {"view_images": {"front": {"image_url": "generated/preview/hero.png",
                                     "watermarked_url": "watermarked/hero.png"}}}
    out = components.enumerate_components(collected, gen)
    labels = {c["label"] for c in out}
    paths = {c["path"] for c in out}

    assert "uploads/logo.png" in paths
    assert "composite/f.png" in paths and "composite/b.png" in paths
    assert "uploads/lay_f.png" in paths
    assert "uploads/el1.png" in paths
    assert "generated/preview/hero.png" in paths      # rendered image included when present
    assert "https://cdn/x.png" not in paths           # external element skipped
    assert all("path" in c and "label" in c for c in out)
    assert any("Uploaded" in lbl for lbl in labels)


def test_enumerate_components_empty_without_render():
    assert components.enumerate_components({}, None) == []
```

- [ ] **Step 2:** Run it — expect FAIL (no module `components`).
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_components.py -v
```

- [ ] **Step 3:** Implement `backend/app/services/components.py`:
```python
"""Enumerate the complete uploaded/derived component set for a session.

Used by the sales notification (attachments) and the admin quote-requests view
(download links). Returns storage PATHS only — external URLs (Shopify product
photos, stub placeholders) are excluded because they aren't ours to hand over and
can't be downloaded via storage.download_asset. PII-safe: paths carry no customer
identity.
"""
from __future__ import annotations

_FACES = ("front", "back", "left", "right")


def _is_storage_path(value) -> bool:
    return bool(value) and isinstance(value, str) and not value.startswith("http")


def enumerate_components(collected: dict, generation: dict | None = None) -> list[dict]:
    """Every downloadable component for a session, as ``{"label", "path"}``.

    Sources, in a stable order: the uploaded asset, each face's flattened canvas
    preview, each face's layout guide, each element's own asset, and (when a
    render exists) the rendered generation image per view.
    """
    collected = collected or {}
    out: list[dict] = []

    up = collected.get("uploaded_asset_path")
    if _is_storage_path(up):
        out.append({"label": "Uploaded logo/artwork", "path": up})

    previews = collected.get("canvas_previews") or {}
    for face in _FACES:
        p = previews.get(face)
        if _is_storage_path(p):
            out.append({"label": f"Canvas preview — {face}", "path": p})

    layouts = collected.get("canvas_layouts") or {}
    for face in _FACES:
        p = layouts.get(face)
        if _is_storage_path(p):
            out.append({"label": f"Layout guide — {face}", "path": p})

    for i, el in enumerate(collected.get("elements") or [], start=1):
        p = el.get("asset_path")
        if _is_storage_path(p):
            out.append({"label": f"Element {i} asset", "path": p})

    if generation:
        views = generation.get("view_images") or {}
        for face in _FACES:
            entry = views.get(face) or {}
            p = entry.get("image_url") or entry.get("watermarked_url")
            if _is_storage_path(p):
                out.append({"label": f"Rendered — {face}", "path": p})

    return out
```

- [ ] **Step 4:** Run it — expect PASS.
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_components.py -v
```

- [ ] **Step 5:** Commit.
```bash
cd backend && git add app/services/components.py tests/test_components.py && git commit -m "feat(quote): enumerate downloadable components per session (C5)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: C2/C3 — email templates + send functions

Adds the customer reference email (no design image) and the sales quote-request email (summary + component attachments), plus their prompt templates.

**Files:**
- Modify: `backend/app/prompts.py` (add templates after `SALES_QUOTE_CONFIRMED_EMAIL_BODY` ~line 801)
- Modify: `backend/app/services/email.py` (add `send_quote_reference_email` + `send_quote_request_to_sales` after `send_quote_confirmation_to_sales` ~line 287)
- Test: `backend/tests/test_quote_emails.py` (Create)

**Interfaces:**
- Produces: `email.send_quote_reference_email(to, name, reference_code, store_name, primary_colour) -> bool`; `email.send_quote_request_to_sales(recipient, reference_code, store_name, customer_email, collected, attachments) -> bool`
- Consumes: `prompts.QUOTE_REFERENCE_EMAIL_*`, `prompts.SALES_QUOTE_REQUEST_EMAIL_*`, `email._branded`, `email._dispatch`

- [ ] **Step 1:** Write the failing test. Create `backend/tests/test_quote_emails.py`:
```python
"""Customer reference email (no image) + sales quote-request email (C2/C3)."""
from __future__ import annotations

from app.services import email as email_service


def test_reference_email_carries_code_and_no_image(monkeypatch):
    captured = {}
    def _dispatch(to, subject, html, attachments=None):
        captured.update(to=to, subject=subject, html=html, attachments=attachments)
        return True
    monkeypatch.setattr(email_service, "_dispatch", _dispatch)

    ok = email_service.send_quote_reference_email(
        "ann@example.com", "Ann", "MH-BCDFGH",
        store_name="MadHats", primary_colour="#ff5c00",
    )
    assert ok is True
    assert "MH-BCDFGH" in captured["html"]
    assert captured["attachments"] is None        # no design image to the customer
    assert "Ann" in captured["html"]


def test_sales_request_email_attaches_components(monkeypatch):
    captured = {}
    def _send(to, subject, html, attachments=None):
        captured.update(to=to, subject=subject, html=html, attachments=attachments)
        return True
    monkeypatch.setattr(email_service, "_dispatch", _send)

    attachments = [{"filename": "c0.png", "content": "AAAA",
                    "content_type": "image/png"}]
    ok = email_service.send_quote_request_to_sales(
        "sales@store.com", "MH-BCDFGH", "MadHats", "ann@example.com",
        {"quantity": 24, "needed_by": "2-4 weeks", "purpose": "team",
         "decoration_type": "embroidery",
         "brief_notes": ["Decoration method: embroidery"]},
        attachments,
    )
    assert ok is True
    assert captured["to"] == "sales@store.com"
    assert "MH-BCDFGH" in captured["html"]
    assert "24" in captured["html"] and "2-4 weeks" in captured["html"]
    assert captured["attachments"] == attachments


def test_sales_request_email_no_recipient_returns_false(monkeypatch):
    monkeypatch.setattr(email_service, "_dispatch", lambda *a, **k: True)
    assert email_service.send_quote_request_to_sales(
        None, "MH-X", "MadHats", "a@b.com", {}, []) is False
```

- [ ] **Step 2:** Run it — expect FAIL (functions don't exist).
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_quote_emails.py -v
```

- [ ] **Step 3:** Add the templates in `backend/app/prompts.py`, after `SALES_QUOTE_CONFIRMED_EMAIL_BODY` (~line 801):
```python
# Customer-facing reference email — quote-gated flow. NO design image; the
# customer only ever receives their tracking reference. Rendered inside the
# BRANDED_EMAIL_HTML shell. Filled with .format(name=, reference_code=).
QUOTE_REFERENCE_EMAIL_SUBJECT = "We've received your request — your MadHats reference"

QUOTE_REFERENCE_EMAIL_BODY = """Hi {name},

Thanks for your request! We've received your design and our team is on it.

Your reference is: {reference_code}

Quote the reference above if you get in touch. We'll be in contact soon with a
quote for your caps.

— Ricardo, MadHats AI Design Studio
"""

# Internal sales notification — an explicit customer quote request. Summary only;
# the uploaded components ride along as attachments (see email.send_quote_request_to_sales).
# Filled with .format(reference_code=, store_name=, customer_email=, quantity=,
# needed_by=, purpose=, decoration=, notes=).
SALES_QUOTE_REQUEST_EMAIL_SUBJECT = "Quote request {reference_code} — {store_name}"

SALES_QUOTE_REQUEST_EMAIL_BODY = """A customer requested a quote via the AI Design Studio.

Reference: {reference_code}
Store: {store_name}
Customer email: {customer_email}

Quantity: {quantity}
Needed by: {needed_by}
Purpose: {purpose}
Decoration method(s): {decoration}

Notes:
{notes}

All uploaded design components are attached. Prepare and send the quote directly
to the customer, quoting the reference above.
"""
```

- [ ] **Step 4:** Add the send functions in `backend/app/services/email.py`, after `send_quote_confirmation_to_sales` (~line 287):
```python
def send_quote_reference_email(
    to: str,
    name: str,
    reference_code: str,
    store_name: str = "MadHats",
    primary_colour: str = "#ff5c00",
) -> bool:
    """Email the customer their tracking reference — quote-gated flow, no image."""
    text = prompts.QUOTE_REFERENCE_EMAIL_BODY.format(name=name, reference_code=reference_code)
    esc = html_lib.escape(text).replace(
        html_lib.escape(reference_code),
        f'<strong style="font-size:18px;letter-spacing:1px;">{html_lib.escape(reference_code)}</strong>',
    )
    body = f"<p style='white-space:pre-wrap'>{esc}</p>"
    return _dispatch(
        to,
        prompts.QUOTE_REFERENCE_EMAIL_SUBJECT,
        _branded(store_name, primary_colour, body),
    )


def send_quote_request_to_sales(
    recipient: str | None,
    reference_code: str,
    store_name: str,
    customer_email: str,
    collected: dict,
    attachments: list[dict] | None = None,
) -> bool:
    """Notify sales of an explicit quote request, with all components attached.

    Best-effort like every other send here. Returns False (no send) when the
    store has no sales_notification_email configured — we never fall back to a
    global address for a store-scoped lead.
    """
    if not recipient:
        log.info("sales_quote_request_skipped_no_recipient")
        return False
    notes = "; ".join(
        str(n).strip() for n in (collected.get("brief_notes") or []) if str(n).strip()
    ) or "—"
    subject = prompts.SALES_QUOTE_REQUEST_EMAIL_SUBJECT.format(
        reference_code=reference_code, store_name=store_name,
    )
    text = prompts.SALES_QUOTE_REQUEST_EMAIL_BODY.format(
        reference_code=reference_code,
        store_name=store_name,
        customer_email=customer_email,
        quantity=collected.get("quantity", "—"),
        needed_by=collected.get("needed_by", "—"),
        purpose=collected.get("purpose", "—"),
        decoration=collected.get("decoration_type", "—"),
        notes=notes,
    )
    html = "<pre style='font-family:inherit;white-space:pre-wrap'>" + html_lib.escape(text) + "</pre>"
    return _dispatch(recipient, subject, html, attachments=attachments or None)
```

- [ ] **Step 5:** Run it — expect PASS.
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_quote_emails.py -v
```

- [ ] **Step 6:** Commit.
```bash
cd backend && git add app/prompts.py app/services/email.py tests/test_quote_emails.py && git commit -m "feat(quote): customer reference + sales quote-request emails (C2/C3)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: C2/C3 — `maybe_send_quote_confirmation` primitive + verification trigger

The idempotent convergence primitive: on `verified AND quote_requested AND not already sent`, email the customer their reference and notify sales with the components attached, then set the dedup flag. Wired into `confirm_verification`.

**Files:**
- Modify: `backend/app/services/delivery.py` (add `maybe_send_quote_confirmation` after `backfill_pending` ~line 412)
- Modify: `backend/app/api/routes/leads.py` (call it in `confirm_verification` after `maybe_send_preview` ~line 135)
- Test: `backend/tests/test_delivery_quote_gate.py` (add cases)

**Interfaces:**
- Produces: `delivery.maybe_send_quote_confirmation(session_id: str) -> bool`
- Consumes: `leads`(reference_code/email_verified/quote_requested/quote_confirmation_sent), `components.enumerate_components`, `storage.download_asset`, `email.send_quote_reference_email`, `email.send_quote_request_to_sales`, `stores.get_store`

- [ ] **Step 1:** Add the failing tests to `backend/tests/test_delivery_quote_gate.py`:
```python
def _quote_tables(**over):
    lead = {"id": "lead-1", "session_id": "sess-1", "name": "Ann", "email": "a@b.com",
            "email_verified": True, "quote_requested": True, "reference_code": "MH-BCDFGH",
            "quote_confirmation_sent": False, "created_at": "2026-07-24T00:00:00Z"}
    lead.update(over.get("lead", {}))
    session = {"id": "sess-1", "store_id": "store-1",
               "collected": {"quote_requested": True, "quantity": 24,
                             "uploaded_asset_path": "uploads/logo.png"}}
    return {"leads": [lead], "design_sessions": [session],
            "generations": over.get("generations", [])}, lead


def test_quote_confirmation_sends_once_and_sets_flag(monkeypatch):
    tables, lead = _quote_tables()
    fake = _FakeSB(tables)
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)
    monkeypatch.setattr(delivery, "get_store", lambda sid: {
        "id": "store-1", "name": "MadHats", "brand": {},
        "sales_notification_email": "sales@store.com"})
    monkeypatch.setattr(delivery.storage, "download_asset", lambda p: b"BYTES")
    cust, sales = [], []
    from app.services import email as email_service
    monkeypatch.setattr(email_service, "send_quote_reference_email",
                        lambda *a, **k: cust.append(a) or True)
    monkeypatch.setattr(email_service, "send_quote_request_to_sales",
                        lambda *a, **k: sales.append((a, k)) or True)

    assert delivery.maybe_send_quote_confirmation("sess-1") is True
    assert len(cust) == 1 and len(sales) == 1
    # components attached to sales
    assert sales[0][0][5]  # attachments list arg is non-empty
    assert lead["quote_confirmation_sent"] is True
    # Second call is a no-op (flag set).
    assert delivery.maybe_send_quote_confirmation("sess-1") is False
    assert len(cust) == 1


def test_quote_confirmation_requires_verified_and_requested(monkeypatch):
    tables, _ = _quote_tables(lead={"email_verified": False})
    fake = _FakeSB(tables)
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)
    assert delivery.maybe_send_quote_confirmation("sess-1") is False
```

- [ ] **Step 2:** Run it — expect FAIL (no `maybe_send_quote_confirmation`).
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_delivery_quote_gate.py -k quote_confirmation -v
```

- [ ] **Step 3:** Implement `maybe_send_quote_confirmation` in `backend/app/services/delivery.py`, after `backfill_pending` (~line 412). It reuses the module imports already present (`storage`, `get_store` via local import, `components`):
```python
def maybe_send_quote_confirmation(session_id: str) -> bool:
    """Send the customer reference email + sales notification, once. Idempotent.

    Gates (ALL required): a lead exists, email_verified, quote_requested, a
    reference_code is allocated, and quote_confirmation_sent is False. On success
    the customer is emailed their reference (no design image) and sales is emailed
    a summary with every uploaded component attached, then the dedup flag is set.

    This is the quote-gated analogue of maybe_send_preview: the two async tracks
    (explicit quote request + email verification) converge here, whichever
    finishes last. Best-effort sends; the flag is set only after the customer
    email dispatches, so a failed run stays retriable. PII-safe: session/lead ids
    only.
    """
    from app.services import components as components_service  # noqa: PLC0415
    from app.services import email as email_service  # noqa: PLC0415
    from app.services.stores import get_store  # noqa: PLC0415

    sb = get_supabase()
    lead = _lead_for_session(session_id)
    if not lead:
        return False
    if not (lead.get("email_verified") and lead.get("quote_requested")):
        return False
    if not lead.get("reference_code"):
        return False
    if lead.get("quote_confirmation_sent"):
        return False

    session_res = (
        sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    )
    session = session_res.data[0] if session_res.data else {}
    collected = session.get("collected") or {}

    store = get_store(session.get("store_id")) if session.get("store_id") else None
    brand = (store or {}).get("brand") or {}
    store_name = (store or {}).get("name") or "MadHats"
    primary = brand.get("primary_colour") or "#ff5c00"

    customer_ok = email_service.send_quote_reference_email(
        lead["email"], lead.get("name") or "there", lead["reference_code"],
        store_name=store_name, primary_colour=primary,
    )

    # Build component attachments (base64), reusing the download primitive.
    import base64  # noqa: PLC0415

    attachments: list[dict] = []
    for comp in components_service.enumerate_components(collected):
        data = storage.download_asset(comp["path"])
        if not data:
            continue
        attachments.append(
            {
                "filename": comp["path"].rsplit("/", 1)[-1],
                "content": base64.b64encode(data).decode("ascii"),
                "content_type": "image/png",
            }
        )
    email_service.send_quote_request_to_sales(
        (store or {}).get("sales_notification_email"),
        lead["reference_code"], store_name, lead["email"], collected, attachments,
    )

    if not customer_ok:
        # Leave the flag unset so a later retry (backfill / re-verify) re-sends.
        log.warning("quote_reference_email_failed", session_id=session_id)
        return False

    sb.table("leads").update(
        {"quote_confirmation_sent": True}
    ).eq("id", lead["id"]).execute()
    log.info("quote_confirmation_delivered", session_id=session_id)  # no PII
    return True
```

- [ ] **Step 4:** Wire it into verification. In `backend/app/api/routes/leads.py`, inside `confirm_verification`, after the `maybe_send_preview` try/except block (~line 135, before the `if not preview_sent:` resume-email block), add:
```python
    # Quote-gated flow (C2/C3): the customer never gets the design — email them
    # their tracking reference + notify sales, once. Best-effort, idempotent.
    try:
        delivery.maybe_send_quote_confirmation(session_id)
    except Exception as exc:  # noqa: BLE001
        log.error("quote_confirmation_failed", lead_id=lead_id, error_type=type(exc).__name__)
```

- [ ] **Step 5:** Run it — expect PASS. Re-run the leads-verify route suite to confirm no regression.
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_delivery_quote_gate.py tests/test_leads_verify_route.py -v
```

- [ ] **Step 6:** Commit.
```bash
cd backend && git add app/services/delivery.py app/api/routes/leads.py tests/test_delivery_quote_gate.py && git commit -m "feat(quote): maybe_send_quote_confirmation + verification trigger (C2/C3)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: C4 — render-on-demand admin endpoint

A lean re-enqueue helper returning the `job_id`, plus `POST /admin/quote-requests/{lead_id}/render` gated by X-Admin-Secret + X-Store-Key. Reuses `_run_generation` (so the C6 fix, Tasks 9–11, applies automatically).

**Files:**
- Modify: `backend/app/api/routes/generate.py` (`_enqueue_generation` returns job_id; add `enqueue_render_for_session`)
- Modify: `backend/app/api/routes/admin_leads.py` (add render endpoint; needs `BackgroundTasks`, `require_store`)
- Test: `backend/tests/test_admin_quote_render.py` (Create)

**Interfaces:**
- Produces: `generate.enqueue_render_for_session(background, session) -> str`; `POST /admin/quote-requests/{lead_id}/render` → `{"job_id": str}`
- Consumes: `generate._run_generation`, `prompt_builder.build_params`/`build_prompt`, `require_admin`, `require_store`

- [ ] **Step 1:** Write the failing test. Create `backend/tests/test_admin_quote_render.py`:
```python
"""POST /admin/quote-requests/{lead_id}/render triggers an on-demand render (C4)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, rows, sink):
        self._table, self._rows, self._sink = table, rows, sink
        self._pending_insert = None

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def insert(self, payload):
        self._pending_insert = payload
        return self

    def execute(self):
        if self._pending_insert is not None:
            row = {"job_id": "job-xyz", "id": "gen-row-1", **self._pending_insert}
            self._sink.append(row)
            return _Result([row])
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, tables):
        self._tables = tables
        self.sink: list = []

    def table(self, name):
        return _Query(name, list(self._tables.get(name, [])), self.sink)


@pytest.fixture()
def client(monkeypatch):
    from app.api.routes import admin_leads, generate
    from app.main import app

    fake = _FakeSB({
        "leads": [{"id": "lead-1", "session_id": "sess-1"}],
        "design_sessions": [{"id": "sess-1", "store_id": "store-1",
                             "product_ref": {"reference_image_url": "https://x/f.png"},
                             "collected": {"flow_mode": "canvas", "elements": []}}],
    })
    monkeypatch.setattr(admin_leads, "get_supabase", lambda: fake)
    monkeypatch.setattr(generate, "get_supabase", lambda: fake)
    # Resolve the store from the X-Store-Key header to store-1.
    from app.api import deps
    monkeypatch.setattr(deps, "resolve_store", lambda k: {"id": "store-1"})
    # Don't actually run the background render.
    monkeypatch.setattr(generate, "_run_generation", lambda **k: None)
    return TestClient(app)


def test_render_requires_admin(client):
    r = client.post("/admin/quote-requests/lead-1/render",
                    headers={"X-Store-Key": "mh_pk"})
    assert r.status_code == 401


def test_render_enqueues_and_returns_job(client):
    r = client.post(
        "/admin/quote-requests/lead-1/render",
        headers={"X-Admin-Secret": settings.admin_secret, "X-Store-Key": "mh_pk"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["job_id"] == "job-xyz"


def test_render_rejects_cross_store(client, monkeypatch):
    from app.api import deps
    monkeypatch.setattr(deps, "resolve_store", lambda k: {"id": "other-store"})
    r = client.post(
        "/admin/quote-requests/lead-1/render",
        headers={"X-Admin-Secret": settings.admin_secret, "X-Store-Key": "mh_pk"},
    )
    assert r.status_code == 404
```

- [ ] **Step 2:** Run it — expect FAIL (404 route not found / no endpoint).
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_admin_quote_render.py -v
```

- [ ] **Step 3:** Make `_enqueue_generation` return the job id and add the reusable render helper in `backend/app/api/routes/generate.py`. Change the end of `_enqueue_generation` (~line 630) so the final statement returns `job_id`:
```python
    background.add_task(
        _run_generation,
        job_id=job_id,
        generation_id=generation_id,
        session_id=session["id"],
        store_id=session.get("store_id"),
        tier=tier,
        provider_tier=provider_tier,
        prompt=prompt,
        product_ref=product_ref,
        collected=collected,
        params=params,
    )
    return job_id
```
Add the public wrapper immediately after `_enqueue_generation`:
```python
def enqueue_render_for_session(background: BackgroundTasks, session: dict) -> str:
    """Admin-triggered on-demand render (C4). Reuses the canvas render pipeline
    with the C6 fix applied. Lean like the watchdog re-enqueue — it deliberately
    skips the per-customer caps + moderation of _start_generation, because this is
    an internal, already-validated design, not a new customer request. Returns the
    new job_id so the admin panel can poll generation status."""
    return _enqueue_generation(background, session, tier="preview")
```
Also add `BackgroundTasks` to the FastAPI import if not already imported (it is — line 6).

- [ ] **Step 4:** Add the render endpoint in `backend/app/api/routes/admin_leads.py`. Update the imports at the top:
```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.deps import require_admin, require_store
from app.api.routes import generate
from app.db import get_supabase
```
Then add the endpoint after `list_quote_requests`:
```python
@router.post("/admin/quote-requests/{lead_id}/render")
async def render_quote_request(
    lead_id: str,
    background: BackgroundTasks,
    store: dict = Depends(require_store),
) -> dict:
    """Sales-triggered on-demand render for a quote request (C4).

    Store-scoped: the lead's session must belong to the X-Store-Key store. Reuses
    the canvas render pipeline (with the C6 fix). Returns the job_id to poll.
    """
    sb = get_supabase()
    lead_res = sb.table("leads").select("*").eq("id", lead_id).limit(1).execute()
    if not lead_res.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    session_id = lead_res.data[0]["session_id"]

    sess_res = (
        sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    )
    session = sess_res.data[0] if sess_res.data else None
    if not session or session.get("store_id") != store["id"]:
        raise HTTPException(status_code=404, detail="Quote request not found for this store")

    job_id = generate.enqueue_render_for_session(background, session)
    return {"job_id": job_id}
```
Note: the router-level `dependencies=[Depends(require_admin)]` already gates every route here, so the render endpoint is admin- AND store-gated.

- [ ] **Step 5:** Run it — expect PASS.
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_admin_quote_render.py -v
```

- [ ] **Step 6:** Commit.
```bash
cd backend && git add app/api/routes/generate.py app/api/routes/admin_leads.py tests/test_admin_quote_render.py && git commit -m "feat(quote): admin render-on-demand endpoint for quote requests (C4)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: C6.1 — `_map_views` stops fabricating angle aliases

`catalogue_sync._map_views` no longer fills `back`/`left`/`right` with positional/front images. Only genuine keyword-matched angles (and `front`) are recorded; a face with no real photo is left absent.

**Files:**
- Modify: `backend/app/services/catalogue_sync.py` (`_map_views` lines 62–80)
- Test: `backend/tests/test_catalogue_sync_views.py` (Create)

**Interfaces:**
- Consumes: `image_srcs: list[str]`
- Produces: `_map_views(image_srcs) -> dict` (only real angles + front)

- [ ] **Step 1:** Write the failing test. Create `backend/tests/test_catalogue_sync_views.py`:
```python
"""_map_views records only genuine angles + front — no fabricated aliases (C6.1)."""
from __future__ import annotations

from app.services.catalogue_sync import _map_views


def test_no_genuine_angles_records_only_front():
    srcs = ["https://x/cap-1.jpg", "https://x/cap-2.jpg", "https://x/cap-3.jpg"]
    views = _map_views(srcs)
    assert views == {"front": "https://x/cap-1.jpg"}
    assert "back" not in views and "left" not in views and "right" not in views


def test_keyword_matched_angles_are_kept():
    srcs = [
        "https://x/cap-front.jpg",
        "https://x/cap-back.jpg",
        "https://x/cap-left-side.jpg",
    ]
    views = _map_views(srcs)
    assert views["front"] == "https://x/cap-front.jpg"
    assert views["back"] == "https://x/cap-back.jpg"
    assert views["left"] == "https://x/cap-left-side.jpg"
    assert "right" not in views      # no genuine right angle -> absent


def test_empty_srcs_is_empty():
    assert _map_views([]) == {}
```

- [ ] **Step 2:** Run it — expect FAIL (current code fabricates back/left/right).
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_catalogue_sync_views.py -v
```

- [ ] **Step 3:** Replace `_map_views` in `backend/app/services/catalogue_sync.py` (lines 62–80) with:
```python
def _map_views(image_srcs: list[str]) -> dict:
    """Map product photos to angle keys by filename keyword, plus front.

    Only GENUINE, keyword-matched angles are recorded — we no longer fabricate
    back/left/right from arbitrary positional images. A decorated face with no
    real per-angle photo is left ABSENT here, so the canvas render loop
    (generate.py) can SKIP it rather than compositing a back decoration onto a
    front-facing cap (C6.1). Front is always available — it is the reference
    photo (image_srcs[0]).
    """
    views: dict[str, str] = {}
    angle_kw = {
        "front": ["front"],
        "back": ["back", "rear"],
        "left": ["left", "side"],
        "right": ["right", "angled"],
    }
    for src in image_srcs:
        low = src.lower()
        for key, kws in angle_kw.items():
            if key not in views and any(k in low for k in kws):
                views[key] = src
    if image_srcs:
        views.setdefault("front", image_srcs[0])
    return views
```

- [ ] **Step 4:** Run it — expect PASS. Re-run the catalogue-sync suite if one exists.
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_catalogue_sync_views.py -v && CANVAS_ORCHESTRATOR_V2=false pytest -k catalogue -q
```

- [ ] **Step 5:** Commit.
```bash
cd backend && git add app/services/catalogue_sync.py tests/test_catalogue_sync_views.py && git commit -m "fix(gen): _map_views stops fabricating back/left/right aliases (C6.1)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: C6.2 — skip non-front faces without a genuine angle + render notes

Adds a `generations.render_notes` column and makes `_run_generation`'s canvas branch skip decorated non-front faces lacking a genuine angle (recording a per-request note). The front hero always renders.

**Files:**
- Create: `backend/supabase/migrations/20260724000002_generation_render_notes.sql`
- Modify: `backend/app/api/routes/generate.py` (`_run_generation` canvas branch ~lines 385–395; persist `render_notes` at completion ~line 468; add `_has_genuine_angle` helper)
- Test: `backend/tests/test_canvas_generation.py` (add case)

**Interfaces:**
- Produces: `generate._has_genuine_angle(product_ref, view) -> bool`; `generations.render_notes` populated with skipped-face notes
- Consumes: `product_ref["view_images"]`, `prompt_builder.render_views`

- [ ] **Step 1:** Write the failing test. Add to `backend/tests/test_canvas_generation.py` (import the helper directly — pure, no DB):
```python
def test_has_genuine_angle_front_always_true_others_need_photo():
    from app.api.routes import generate
    product_ref = {"reference_image_url": "https://x/front.png",
                   "view_images": {"front": "https://x/front.png",
                                   "back": "https://x/back.png"}}
    assert generate._has_genuine_angle(product_ref, "front") is True
    assert generate._has_genuine_angle(product_ref, "back") is True
    # left/right absent from view_images -> not genuine (front-alias forbidden)
    assert generate._has_genuine_angle(product_ref, "left") is False
    assert generate._has_genuine_angle(product_ref, "right") is False


def test_canvas_render_skips_faces_without_a_genuine_angle():
    """A back-decorated element on a product with no back photo is skipped, and a
    note is recorded — the front hero still renders."""
    from app.api.routes import generate
    product_ref = {"reference_image_url": "https://x/front.png", "view_images": {}}
    collected = {
        "flow_mode": "canvas",
        "elements": [
            {"type": "text", "content": "F", "placement_zone": "front_panel"},
            {"type": "text", "content": "B", "placement_zone": "back"},
        ],
    }
    kept, skipped = generate._canvas_views_split(collected, product_ref)
    assert kept == ["front"]
    assert skipped == ["back"]
```

- [ ] **Step 2:** Run it — expect FAIL (helpers don't exist).
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_canvas_generation.py -k genuine_angle -v
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_canvas_generation.py -k skips_faces -v
```

- [ ] **Step 3:** Write the migration `backend/supabase/migrations/20260724000002_generation_render_notes.sql`:
```sql
-- C6.2: per-render operational notes (e.g. "back face not rendered — no back
-- angle photo for this product"). Surfaced to sales in the admin quote-requests
-- view. Design data only, no customer PII.
alter table generations add column if not exists render_notes jsonb;
```

- [ ] **Step 4:** Add the helpers + wire them into `backend/app/api/routes/generate.py`. Add the helpers just above `_run_generation` (~line 345):
```python
def _has_genuine_angle(product_ref: dict, view: str) -> bool:
    """True when a view has a REAL reference photo to composite onto.

    Front is always genuine (reference_image_url is always present). A non-front
    view is genuine only when it is an explicit key in view_images — after the
    C6.1 fix that means a keyword-matched product angle or a blank session's real
    per-angle blank, never a fabricated front alias.
    """
    if view == prompt_builder.PRIMARY_VIEW:
        return True
    return bool((product_ref.get("view_images") or {}).get(view))


def _canvas_views_split(collected: dict, product_ref: dict) -> tuple[list[str], list[str]]:
    """Partition the canvas's decorated views into (kept, skipped).

    Kept views have a genuine angle; skipped ones (decorated but no real photo)
    are dropped so a back decoration is never composited onto the front cap. The
    front hero is always kept."""
    all_views = prompt_builder.render_views(collected)
    kept = [v for v in all_views if _has_genuine_angle(product_ref, v)]
    skipped = [v for v in all_views if v not in kept]
    return kept, skipped
```
Replace the `elif is_canvas:` branch (~lines 385–394) with:
```python
    elif is_canvas:
        # Every decorated face is AI-rendered, BUT only faces with a genuine
        # reference angle — a decorated non-front face with no real photo is
        # skipped (C6.2) rather than composited onto the wrong angle. The front
        # hero always renders.
        views, _skipped_views = _canvas_views_split(collected, product_ref)
        prev_views = {}
    else:
        views = prompt_builder.render_views(collected)
        prev_views = {}
        _skipped_views = []
```
Add `_skipped_views = []` initialisation for the edit branch too — change the `if is_edit:` block's start (~line 381) to also set it:
```python
    is_edit = tier == "edit"
    _skipped_views: list[str] = []
    if is_edit:
```
Then record the notes at completion. In the completion `sb.table("generations").update({...})` block (~line 468), add a `render_notes` key:
```python
        render_notes = None
        if _skipped_views:
            render_notes = {
                "skipped_views": _skipped_views,
                "message": "; ".join(
                    f"{v} face not rendered — no {v} angle photo for this product"
                    for v in _skipped_views
                ),
            }
        sb.table("generations").update(
            {
                "status": "complete",
                "model": anchor["model"],
                "image_url": hero_entry["image_url"],
                "watermarked_url": hero_entry["watermarked_url"],
                "view_images": view_images,
                "prompt_hash": anchor["key"],
                "cost_usd": sum(r.get("cost_usd") or 0 for r in results),
                "latency_ms": max((r.get("latency_ms") or 0 for r in results), default=0),
                "attempts": attempts,
                "render_notes": render_notes,
            }
        ).eq("job_id", job_id).execute()
```

- [ ] **Step 5:** Run it — expect PASS. Re-run the full canvas-generation suite.
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_canvas_generation.py -v
```

- [ ] **Step 6:** Commit.
```bash
cd backend && git add app/api/routes/generate.py supabase/migrations/20260724000002_generation_render_notes.sql tests/test_canvas_generation.py && git commit -m "fix(gen): skip canvas faces with no genuine angle; record render_notes (C6.2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: C6.3 — explicit front-to-back z-order in the per-face prompt

Injects a stacking-order sentence into each multi-element face's prompt so overlap doesn't depend solely on the grey layout guide. Uses each element's `canvas.z` (higher = on top).

**Files:**
- Modify: `backend/app/services/prompt_builder.py` (add `_element_label` + `_zorder_note`; inject in `build_view_prompt` ~line 377)
- Test: `backend/tests/test_prompt_builder.py` (add case)

**Interfaces:**
- Produces: `prompt_builder._zorder_note(elements) -> str`
- Consumes: element `canvas.z`, `type`, `content`

- [ ] **Step 1:** Write the failing test. Add to `backend/tests/test_prompt_builder.py`:
```python
def test_build_view_prompt_injects_front_to_back_zorder():
    from app.services import prompt_builder
    from app.services.image.image_provider import GenerationParams

    collected = {
        "flow_mode": "canvas",
        "elements": [
            {"type": "text", "content": "BOTTOM", "placement_zone": "front_panel",
             "canvas": {"face": "front", "z": 0}},
            {"type": "logo", "placement_zone": "front_panel",
             "canvas": {"face": "front", "z": 5}},
        ],
    }
    product_ref = {"reference_image_url": "https://x/front.png"}
    params = prompt_builder.build_params(collected, "preview")
    prompt = prompt_builder.build_view_prompt(collected, product_ref, params, "front")

    assert "Layering" in prompt or "overlap" in prompt.lower()
    # front-most (higher z) is listed before the lower one
    assert prompt.index("uploaded") < prompt.index("BOTTOM")


def test_zorder_note_empty_for_single_element():
    from app.services import prompt_builder
    assert prompt_builder._zorder_note([{"type": "text", "content": "x"}]) == ""
```

- [ ] **Step 2:** Run it — expect FAIL (`_zorder_note` doesn't exist / not injected).
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_prompt_builder.py -k zorder -v
```

- [ ] **Step 3:** Add the helpers in `backend/app/services/prompt_builder.py`, immediately after `_element_line` (~line 175):
```python
def _element_label(el: dict) -> str:
    """A short identity for an element, for the layering note."""
    etype = el.get("type")
    if etype == "text":
        return f'text "{el.get("content", "")}"'
    if etype == "logo":
        return "the uploaded logo/artwork"
    return f"graphic: {el.get('content', '')}" if el.get("content") else "a graphic"


def _zorder_note(elements: list[dict]) -> str:
    """An explicit front-to-back stacking order for a face's elements.

    Overlap survived only in the flattened grey layout guide before; on
    multi-element faces the model misread stacking. This states it in words —
    front-most (drawn on top) first — so the render respects it (C6.3). Notes
    (do-not-render) are excluded; fewer than two visible elements needs no order.
    """
    visible = [e for e in elements if e.get("type") != "note"]
    if len(visible) < 2:
        return ""
    ordered = sorted(
        visible, key=lambda e: (e.get("canvas") or {}).get("z", 0), reverse=True
    )
    lines = "\n".join(f"  {i}. {_element_label(e)}" for i, e in enumerate(ordered, start=1))
    return (
        "Layering / overlap order on this face — front-most (on top) listed first. "
        "Where elements overlap, the earlier item sits over the later one:\n" + lines
    )
```
Inject the note in `build_view_prompt` — replace the `if view_elements:` branch tail (~line 377, the `design_block = _design_block(scoped)` line) so the note is appended:
```python
        design_block = _design_block(scoped)
        zorder = _zorder_note(view_elements)
        if zorder:
            design_block = f"{design_block}\n{zorder}"
```

- [ ] **Step 4:** Run it — expect PASS. Re-run the full prompt-builder suite.
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_prompt_builder.py -v
```

- [ ] **Step 5:** Commit.
```bash
cd backend && git add app/services/prompt_builder.py tests/test_prompt_builder.py && git commit -m "fix(gen): inject explicit front-to-back z-order into per-face prompt (C6.3)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: C7 (backend) — enrich the quote-requests listing + components endpoint

Extends `GET /admin/quote-requests` with the reference, summary fields, latest render info, and per-request downloadable components (via `/media` proxy URLs).

**Files:**
- Modify: `backend/app/api/routes/admin_leads.py` (list output ~lines 41–57; add `GET /admin/quote-requests/{lead_id}/components`)
- Test: `backend/tests/test_admin_leads.py` (add cases)

**Interfaces:**
- Produces: enriched list rows (`reference_code`, `needed_by`, `purpose`, `notes`, `render_status`, `render_notes`); `GET /admin/quote-requests/{lead_id}/components` → `{"components": [{"label", "url"}]}`
- Consumes: `components.enumerate_components`, `storage.media_url`, latest generation row

- [ ] **Step 1:** Write the failing tests. Add to `backend/tests/test_admin_leads.py` (mirror its existing fake-SB fixture; assert the new fields + endpoint):
```python
def test_quote_requests_include_reference_and_summary(admin_client, seed_quote_lead):
    # seed a quote_confirmed lead with a reference + collected summary
    r = admin_client.get("/admin/quote-requests")
    assert r.status_code == 200
    row = r.json()[0]
    assert row["reference_code"] == "MH-BCDFGH"
    assert row["needed_by"] == "2-4 weeks"
    assert row["purpose"] == "team event"
    assert "quantity" in row


def test_components_endpoint_lists_download_urls(admin_client, seed_quote_lead):
    r = admin_client.get("/admin/quote-requests/lead-1/components")
    assert r.status_code == 200
    comps = r.json()["components"]
    assert any(c["label"].startswith("Uploaded") for c in comps)
    assert all(c["url"] for c in comps)


def test_v2_requested_leads_appear_without_quote_confirmed(admin_client, seed_v2_requested_lead):
    """The quote-gated flow sets quote_requested=True and never quote_confirmed —
    the listing must still surface it (widened .or_ filter)."""
    r = admin_client.get("/admin/quote-requests")
    assert r.status_code == 200
    refs = {row.get("reference_code") for row in r.json()}
    assert "MH-REQ222" in refs        # quote_requested-only lead is listed
```
> If `test_admin_leads.py` has no shared fixtures, add a local `_FakeSB` (copy the `_Query`/`_FakeSB` pattern from `test_admin_quote_render.py`) — and because the real query now uses PostgREST `.or_(...)`, add a minimal `.or_()` to the fake `_Query`:
> ```python
>     def or_(self, expr):
>         # minimal "col.eq.true,col2.eq.true" — keep rows truthy on ANY listed col
>         cols = [clause.split(".")[0] for clause in expr.split(",")]
>         self._rows = [r for r in self._rows if any(r.get(c) for c in cols)]
>         return self
> ```
> `seed_quote_lead` seeds `leads` with `quote_confirmed=True`, `reference_code="MH-BCDFGH"`, and a session whose `collected` has `uploaded_asset_path="uploads/logo.png"`, `needed_by`, `purpose`, `quantity`. `seed_v2_requested_lead` seeds a SECOND lead with `quote_confirmed=False`, `quote_requested=True`, `reference_code="MH-REQ222"`. Monkeypatch `admin_leads.get_supabase` and `admin_leads.storage.media_url` (→ `f"/media/{path}"`).

- [ ] **Step 2:** Run it — expect FAIL (fields/endpoint missing).
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_admin_leads.py -k "reference or components" -v
```

- [ ] **Step 3:** Enrich the list + add the components endpoint in `backend/app/api/routes/admin_leads.py`. Add imports at the top:
```python
from fastapi import Request

from app import storage
from app.services import components as components_service
```
Extend each `out.append({...})` in `list_quote_requests` with the new fields:
```python
        out.append(
            {
                "lead_id": lead["id"],
                "session_id": lead["session_id"],
                "reference_code": lead.get("reference_code"),
                "name": lead.get("name"),
                "email": lead.get("email"),
                "phone": lead.get("phone"),
                "notify_by_phone": lead.get("notify_by_phone", False),
                "quote_note": lead.get("quote_note"),
                "quote_confirmed_at": lead.get("quote_confirmed_at"),
                "quote_requested": lead.get("quote_requested", False),
                "product": product_ref.get("name") or product_ref.get("product_id"),
                "decoration_type": collected.get("decoration_type"),
                "placement_zone": collected.get("placement_zone"),
                "quantity": collected.get("quantity"),
                "needed_by": collected.get("needed_by"),
                "purpose": collected.get("purpose"),
                "notes": "; ".join(str(n) for n in (collected.get("brief_notes") or [])) or None,
                "share_token": session.get("share_token"),
            }
        )
```
**Widen the listing filter** — this is essential, not optional. The current query filters `.eq("quote_confirmed", True)` (the emailed-quote-link path). The quote-gated flow's explicit `REQUEST_QUOTE` step sets `quote_requested=True` and the customer **never** clicks an email quote link, so it never becomes `quote_confirmed` — without widening the filter, the new flow's requests are invisible to sales. Replace the `res = (...)` query in `list_quote_requests` (~lines 20–26) with:
```python
    res = (
        sb.table("leads")
        .select("*")
        # Surface BOTH quote signals: the emailed-link confirmation
        # (quote_confirmed) AND the v2 explicit in-chat request (quote_requested
        # — the quote-gated canvas flow, where the customer never gets an email
        # quote link). Order by created_at (present on every row; quote_requested
        # leads have no quote_confirmed_at).
        .or_("quote_confirmed.eq.true,quote_requested.eq.true")
        .order("created_at", desc=True)
        .execute()
    )
```

Add the components endpoint after `list_quote_requests`:
```python
@router.get("/admin/quote-requests/{lead_id}/components")
async def list_quote_components(lead_id: str, request: Request) -> dict:
    """Downloadable component set for a quote request (C5/C7).

    Each component is served through the /media proxy (a same-origin, capability-
    token URL) so an admin <a download> can fetch a private bucket object. Also
    includes the latest render's images when a render exists.
    """
    sb = get_supabase()
    lead_res = sb.table("leads").select("session_id").eq("id", lead_id).limit(1).execute()
    if not lead_res.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    session_id = lead_res.data[0]["session_id"]

    sess = sb.table("design_sessions").select("collected").eq("id", session_id).limit(1).execute()
    collected = (sess.data[0].get("collected") or {}) if sess.data else {}

    gen_res = (
        sb.table("generations")
        .select("*")
        .eq("session_id", session_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    generation = gen_res.data[0] if gen_res.data else None

    base_url = str(request.base_url)
    out = []
    for comp in components_service.enumerate_components(collected, generation):
        out.append({"label": comp["label"], "url": storage.media_url(comp["path"], base_url)})
    return {"components": out}
```

- [ ] **Step 4:** Run it — expect PASS.
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest tests/test_admin_leads.py -v
```

- [ ] **Step 5:** Run the full backend baseline to confirm no regressions across the workstream.
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest -q
```

- [ ] **Step 6:** Commit.
```bash
cd backend && git add app/api/routes/admin_leads.py tests/test_admin_leads.py && git commit -m "feat(quote): admin quote-requests reference/summary + components endpoint (C5/C7)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 13: C7 (frontend) — admin quote-requests view: reference, components, render

Adds the reference column, a per-row expand with the summary + component download list ("download all") + a "Generate render" button that polls status and shows the result.

**Files:**
- Modify: `frontend/src/admin/adminApi.ts` (extend `QuoteRequest` type; add `listQuoteComponents`, `renderQuoteRequest`)
- Modify: `frontend/src/admin/views/QuoteRequestsView.tsx` (reference column + component/render panel)
- Test: `frontend/src/admin/views/QuoteRequestsView.test.tsx` (Create)

**Interfaces:**
- Consumes: `GET /admin/quote-requests`, `GET /admin/quote-requests/{lead_id}/components`, `POST /admin/quote-requests/{lead_id}/render`, `GET /admin/generations` (existing) or `/generate/status/{job_id}` for polling
- Produces: (UI) reference column, component download links, render button

- [ ] **Step 1:** Write the failing test. Create `frontend/src/admin/views/QuoteRequestsView.test.tsx`:
```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QuoteRequestsView } from './QuoteRequestsView'
import * as api from '../adminApi'

describe('QuoteRequestsView', () => {
  beforeEach(() => {
    vi.spyOn(api, 'listQuoteRequests').mockResolvedValue([
      {
        lead_id: 'lead-1', session_id: 'sess-1', reference_code: 'MH-BCDFGH',
        name: 'Ann', email: 'ann@example.com', product: 'Snapback',
        decoration_type: 'embroidery', quantity: 24, needed_by: '2-4 weeks',
        purpose: 'team', quote_confirmed_at: null,
      } as unknown as api.QuoteRequest,
    ])
  })

  it('shows the tracking reference', async () => {
    render(<MemoryRouter><QuoteRequestsView /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('MH-BCDFGH')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2:** Run it — expect FAIL (`reference_code` not on the type / not rendered).
```bash
cd frontend && npx vitest run src/admin/views/QuoteRequestsView.test.tsx
```

- [ ] **Step 3:** Extend the API in `frontend/src/admin/adminApi.ts`. Find the `QuoteRequest` type and add the fields, then add two functions near `listQuoteRequests` (~line 183):
```ts
// Add to the QuoteRequest interface:
//   reference_code?: string | null
//   needed_by?: string | null
//   purpose?: string | null
//   notes?: string | null

export interface QuoteComponent {
  label: string
  url: string | null
}

export function listQuoteComponents(leadId: string): Promise<{ components: QuoteComponent[] }> {
  return request<{ components: QuoteComponent[] }>(`/admin/quote-requests/${leadId}/components`)
}

export function renderQuoteRequest(leadId: string): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(`/admin/quote-requests/${leadId}/render`, { method: 'POST' })
}
```

- [ ] **Step 4:** Add the reference column + an expandable render/components panel in `frontend/src/admin/views/QuoteRequestsView.tsx`. Add a `reference` column at the front of `columns`:
```tsx
    { key: 'reference', header: 'Reference', render: (r) => r.reference_code ?? '—' },
```
Add a per-row action column that lets the admin open the components panel + trigger a render. Insert into `columns` (before the existing `view` column):
```tsx
    {
      key: 'render',
      header: '',
      render: (r) => (
        <RenderCell leadId={r.lead_id} />
      ),
    },
```
And define the `RenderCell` component at the bottom of the file (above the final export or after it):
```tsx
import { listQuoteComponents, renderQuoteRequest, type QuoteComponent } from '../adminApi'

function RenderCell({ leadId }: { leadId: string }) {
  const [components, setComponents] = useState<QuoteComponent[] | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function loadComponents() {
    setBusy(true)
    try {
      const res = await listQuoteComponents(leadId)
      setComponents(res.components)
    } finally {
      setBusy(false)
    }
  }

  async function triggerRender() {
    setBusy(true)
    try {
      const res = await renderQuoteRequest(leadId)
      setJobId(res.job_id)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-1" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={loadComponents}
        disabled={busy}
        className="rounded-lg bg-slate-200 px-3 py-1 text-xs hover:bg-slate-300"
      >
        Components
      </button>
      <button
        type="button"
        onClick={triggerRender}
        disabled={busy}
        className="rounded-lg bg-[#ff5c00] px-3 py-1 text-xs text-white hover:bg-[#e64f00]"
      >
        Generate render
      </button>
      {jobId && <span className="text-[10px] text-slate-500">render queued: {jobId}</span>}
      {components && (
        <div className="mt-1 space-y-1">
          {components.length === 0 && <span className="text-[10px] text-slate-500">no components</span>}
          {components.map((c) => (
            c.url ? (
              <a
                key={c.label}
                href={c.url}
                download
                className="block text-[10px] text-blue-600 underline"
              >
                {c.label}
              </a>
            ) : (
              <span key={c.label} className="block text-[10px] text-slate-400">{c.label}</span>
            )
          ))}
          {components.some((c) => c.url) && (
            <button
              type="button"
              onClick={() => components.forEach((c) => c.url && window.open(c.url, '_blank'))}
              className="text-[10px] text-blue-700 underline"
            >
              Download all
            </button>
          )}
        </div>
      )}
    </div>
  )
}
```
Ensure `useState` is imported (it is, via the existing `useState` import at the top).

- [ ] **Step 5:** Run it — expect PASS.
```bash
cd frontend && npx vitest run src/admin/views/QuoteRequestsView.test.tsx
```

- [ ] **Step 6:** Commit.
```bash
cd frontend && git add src/admin/adminApi.ts src/admin/views/QuoteRequestsView.tsx src/admin/views/QuoteRequestsView.test.tsx && git commit -m "feat(quote): admin quote-requests view — reference, components, render (C7)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Backend baseline stays green:**
```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false pytest -q
```
- [ ] **Targeted frontend (Windows-stall-safe):**
```bash
cd frontend && npx vitest run src/admin/views/QuoteRequestsView.test.tsx
```
- [ ] **Manual smoke (documented, not automated):** with `CANVAS_ORCHESTRATOR_V2=true`, walk a canvas session to REQUEST_QUOTE → tap "Request a quote" → confirm the on-screen reference; verify the email → confirm the customer reference email (no image) + the sales email (summary + attachments); from the admin quote-requests view, click "Generate render" → confirm a render appears and the customer is NOT emailed the design.
```
```
