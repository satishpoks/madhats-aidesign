"""End-to-end walk of the v2 canvas orchestrator's front half.

Drives `orchestrator_v2.handle_message` one turn at a time through the full
name -> intro -> logo loop -> text/shape loop -> quantity -> email -> purpose
-> FINALIZE_CANVAS sequence, asserting the resulting state after every turn.

Reuses the `_FakeSB`/`_FakeTable` fake-Supabase pattern from
`test_orchestrator_v2.py` (there is no conftest.py / pytest fixture registry
in this test suite — each test file wires its own fakes).
"""
import pytest

from app.services.conversation import canvas_steps as cs
from app.services.conversation import orchestrator_v2 as o2
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation.state_machine import ConversationState as S


class _FakeTable:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self._filters = {}

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, *_):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        if self.name == "design_sessions":
            return type("R", (), {"data": [self.store["session"]]})()
        return type("R", (), {"data": []})()

    def update(self, patch):
        self.store["session"].update(patch)
        return self

    def insert(self, rows):
        return self


class _FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeTable(self.store, name)


def _new_store():
    return {
        "session": {
            "id": "s1",
            "state": S.GREETING.value,
            # decoration_options pre-seeded: _prepare_decoration only loads when
            # the key is absent, and this fake session has no store to load from.
            "collected": {"flow_mode": "canvas",
                          "decoration_options": ["Embroidery", "Screen Print"]},
            "upsell_count": 0,
        }
    }


def test_v2_no_longer_uses_the_shared_keyword_matchers():
    """v1 keeps is_affirmative/is_negative (it still routes on them); v2 must
    not import them. `is_negative` matches by substring, so "another" reads as
    "no" — that is what broke the logo loop. Task 8's rewrite also moved the
    name/done-word/face helpers out of orchestrator_v2 entirely: they either
    became registry data (canvas_steps.py) or were replaced by the generic
    first-unmet router (state_machine_v2.py)."""
    with open(o2.__file__, encoding="utf-8") as fh:
        text = fh.read()
    for banned in (
        "is_affirmative", "is_negative", "_apply_v2_fields", "_is_done",
        "_face_from", "_plausible_name", "_NAME_FILLER",
    ):
        assert banned not in text, f"{banned} still referenced in orchestrator_v2"


@pytest.mark.asyncio
async def test_full_v2_walk_using_the_exact_chip_labels(monkeypatch):
    """Drives the exact strings the UI ships. The old e2e hand-picked "yes" to
    dodge the broken "another" chip and stayed green over the bug; this walk
    drives "Yes, another logo" for real.

    The interpreter raises LLMUnavailable for the ENTIRE walk (no mid-walk
    swap) — proving something stronger than a plain e2e: chips resolve by
    deterministic label match, and the three free-text steps (name/email/
    purpose) resolve via `Step.direct_answer`, so the whole v2 front half
    completes with NO model at all.
    """
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "_can_start_design", lambda _sid: True)
    monkeypatch.setattr(
        cs.leads_service, "capture_lead_and_verify",
        lambda s, c, e: ("lead-1", True),
    )

    # The explicit quote request writes to `leads` + converges delivery; neither
    # belongs in a routing walk, so stub the recording and keep the reference.
    monkeypatch.setattr(
        cs.leads_service, "record_quote_request", lambda s, c: "MH-BCDFGH",
    )

    async def _boom(*a, **k):
        raise o2.ie.LLMUnavailable("chips and direct-answer steps need no model")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    walk = [
        ("",                        S.ASK_NAME),
        ("Sam",                     S.SHOW_INTRO),
        ("ok",                      S.ASK_HAS_LOGO),         # intro ack (no slots)
        ("Yes, I have a logo",      S.ASK_LOGO_PLACEMENT),
        ("Front",                   S.LOGO_ADJUST),
        ("Done",                    S.ASK_LOGO_BG),
        ("Yes, remove background",  S.ASK_EMAIL),          # first element placed
        ("sam@example.com",         S.ASK_ANOTHER_LOGO),
        ("Yes, another logo",       S.ASK_LOGO_PLACEMENT),   # THE bug
        ("Back",                    S.LOGO_ADJUST),
        ("Done",                    S.ASK_LOGO_BG),
        ("No, it's fine as is",     S.ASK_ANOTHER_LOGO),
        ("No, that's it",           S.ASK_ADD_DECOR),
        ("Add text",                S.ASK_DECOR_PLACEMENT),
        ("Left",                    S.DECOR_ADJUST),
        ("Done",                    S.ASK_ANYTHING_ELSE),
        ("No, that's everything",   S.ASK_QUANTITY),
        ("50-99",                   S.ASK_DECORATION),
        ("Embroidery",              S.NEEDED_BY),          # single-select; email already captured
        ("ASAP",                    S.ASK_PURPOSE),
        ("for the team",            S.REVIEW_DESIGN),      # pre-submit review
        ("Looks great, send it",    S.REQUEST_QUOTE),      # quote-gated submit
        ("Request a quote",         S.FINALIZE_CANVAS),
    ]

    res = None
    for msg, expected in walk:
        res = await o2.handle_message("s1", msg)
        assert res["state"] == expected.value, f"{msg!r} -> {res['state']}"
        # Every v2-owned turn must carry a directive. A null one means "not a v2
        # turn" to the frontend, which then falls back to v1's whole-rail gating
        # and showed "Design locked in — finishing up" MID-design.
        assert res["data"]["canvas"] is not None, f"{expected.value} had no directive"
        # The auto_open split, asserted through the REAL pipeline (handle_message
        # -> public_data_for), not just directive_for in isolation. Conflating
        # these shipped a bug: the file dialog opening before the face is
        # answered makes the logo land on whatever face is active (default
        # front) instead of the one the customer just named.
        d = res["data"]["canvas"]
        if expected is S.ASK_LOGO_PLACEMENT:
            assert d["allowed_tools"] == ["upload"] and d["auto_open"] is None
        elif expected is S.LOGO_ADJUST:
            assert d["auto_open"] == "upload" and d["show_done"] is True
        elif expected is S.ASK_LOGO_BG:
            # Through the REAL pipeline: the tool must stay allowed or the logo
            # is locked and the "Remove background" toggle is unreachable.
            assert d["allowed_tools"] == ["upload"] and d["auto_open"] is None
        elif expected is S.ASK_DECOR_PLACEMENT:
            assert d["allowed_tools"] == ["text"] and d["auto_open"] is None
        elif expected is S.DECOR_ADJUST:
            assert d["target_face"] == "left"      # the face the customer named

    # The second lap landed on the face the customer actually named.
    assert store["session"]["collected"]["logos"][1]["face"] == "back"

    # The finalize state tells the frontend to flatten + finalize.
    assert res["data"]["trigger_finalize"] is True

    c = store["session"]["collected"]
    assert len(c["logos"]) == 2
    assert [l["face"] for l in c["logos"]] == ["front", "back"]
    assert c["quantity"] == 50
    assert c["logos"][0]["bg"] == "removed"
    assert c["logos"][1]["bg"] == "none"
    assert c["decor_face"] == "left"
    assert c["decoration_types"] == ["Embroidery"]
    assert c["decoration_type"] == "embroidery"   # the pick drives the style
    assert "decoration_mix" not in c              # no mix -> no describe step
    assert c["needed_by"] == "ASAP"


@pytest.mark.asyncio
async def test_v2_mix_branch_asks_the_customer_to_describe_it(monkeypatch):
    """Tapping the mix chip must ask what the mix IS, and bank the answer — with
    the interpreter down for the whole walk, proving the describe step's
    direct_answer carries it (it has no chips, so it cannot nudge instead)."""
    store = _new_store()
    store["session"]["state"] = S.ASK_DECORATION.value
    # email_captured=True: the design phase is already closed (logos_done +
    # decor_done), so ask_email (earlier in the registry) would otherwise
    # intercept before the mix chip's own step is reached.
    store["session"]["collected"].update(
        {"name": "Sam", "intro_ack": True, "has_logo": False, "logos_done": True,
         "pending_logo": None, "decor_done": True, "quantity": 12,
         "email_captured": True}
    )
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "_can_start_design", lambda _sid: True)
    monkeypatch.setattr(
        cs.leads_service, "capture_lead_and_verify",
        lambda s, c, e: ("lead-1", True),
    )

    async def _boom(*a, **k):
        raise o2.ie.LLMUnavailable("the mix chip and its describe step need no model")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    res = await o2.handle_message("s1", cs.MIX_CHIP_LABEL)
    assert res["state"] == S.ASK_DECORATION_MIX.value
    assert "cost per hat" in res["reply"]
    assert not res["data"].get("options")          # free text, no chips to tap
    # Describing the mix must not grow the progress bar — it's a follow-up.
    assert res["data"]["progress"] == v2.progress_v2(S.ASK_DECORATION, {})

    res = await o2.handle_message("s1", "Embroidered logo, printed text on the back")
    # This seed never places a design element (text-only, decor_done set
    # directly) — email rides the design phase now, well before decoration, so
    # with no first-element evidence it stays skipped and routing lands on
    # needed_by. Email-after-first-element is covered directly in
    # test_state_machine_v2.py.
    assert res["state"] == S.NEEDED_BY.value

    c = store["session"]["collected"]
    assert c["decoration_mix_note"] == "Embroidered logo, printed text on the back"
    assert "Decoration method: a mix — Embroidered logo" in c["brief_notes"][-1]
    assert c["decoration_type"] == "embroidery"


@pytest.mark.asyncio
async def test_v2_bg_chip_ships_an_op_to_the_canvas(monkeypatch):
    """The chip and the flag are the same act: tapping yes must reach the canvas.
    Before this, 'Yes, I've ticked it' without ticking rendered no knockout."""
    store = _new_store()
    store["session"]["state"] = S.ASK_LOGO_BG.value
    store["session"]["collected"].update({
        "name": "Sam", "intro_ack": True, "has_logo": True,
        "pending_logo": {"face": "front", "placed": True},
    })
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    out = await o2.handle_message("s1", "Yes, remove background")
    assert out["data"]["canvas_ops"] == [
        {"target": {"kind": "pending_logo", "face": "front"},
         "patch": {"removeBg": True}}
    ]


@pytest.mark.asyncio
async def test_needed_by_accepts_a_free_text_date_voice_path(monkeypatch):
    """B3 voice path: a dictated/transcribed custom date is free text, so it
    flows through the interpreter into the needed_by slot — no chip tapped — and
    advances ASK_PURPOSE. Chip labels from transcribed text are already covered
    by test_full_v2_walk_using_the_exact_chip_labels."""
    store = _new_store()
    store["session"]["state"] = S.NEEDED_BY.value
    store["session"]["collected"].update({
        "name": "Sam", "intro_ack": True, "has_logo": False, "logos_done": True,
        "pending_logo": None, "decor_done": True, "quantity": 12,
        "decoration_done": True, "email_captured": True,
    })
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    async def _fill(step, message, collected):
        assert step.id is S.NEEDED_BY
        return {"needed_by": "the 15th of next month"}
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _fill)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)

    res = await o2.handle_message("s1", "I'd need them by the 15th of next month")
    assert res["state"] == S.ASK_PURPOSE.value
    assert store["session"]["collected"]["needed_by"] == "the 15th of next month"
# --- Workstream D: the store's canvas_flow reaches the router -----------------

def _at_email_store(brand: dict | None):
    """A session parked at ASK_EMAIL with every earlier step answered, so the
    only thing left to route is the configurable tail (purpose).

    `needed_by` (workstream B) and `quote_requested` (workstream C) are locked
    steps that now flank ask_purpose. `design_confirmed` (the pre-submit
    review, also workstream B) is a locked step too, sitting between purpose
    and the quote submit. All three are seeded so the helper's stated
    invariant still holds — otherwise routing stops on one of them and these
    tests would silently stop testing the config wiring at all."""
    store = _new_store()
    store["session"]["state"] = S.ASK_EMAIL.value
    store["session"]["store_id"] = "store-1"
    store["session"]["collected"].update({
        "name": "Sam", "intro_ack": True,
        "logos_done": True, "pending_logo": None, "decor_done": True,
        "quantity": 12, "decoration_done": True,
        "needed_by": "ASAP", "design_confirmed": True, "quote_requested": True,
    })
    return store


def _wire(monkeypatch, store, brand: dict | None):
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "_can_start_design", lambda _sid: True)
    monkeypatch.setattr(o2, "get_store", lambda _id: {
        "id": "store-1", "persona_name": "Ricardo", "brand": brand or {},
    })
    monkeypatch.setattr(
        cs.leads_service, "capture_lead_and_verify",
        lambda s, c, e: ("lead-1", True),
    )

    async def _boom(*a, **k):
        raise o2.ie.LLMUnavailable("ask_email resolves via direct_answer")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    seen: dict = {}
    real_next = v2.next_step

    def _spy(collected, config=None):
        seen["config"] = config
        return real_next(collected, config)
    monkeypatch.setattr(o2.v2, "next_step", _spy)
    return seen


@pytest.mark.asyncio
async def test_orchestrator_threads_store_canvas_flow_config(monkeypatch):
    """With a store config that disables ask_purpose, a session that has
    answered every step up to purpose must route straight to FINALIZE_CANVAS
    rather than asking the disabled step."""
    cfg = {"steps": [{"id": "ask_purpose", "enabled": False}]}
    store = _at_email_store(cfg)
    seen = _wire(monkeypatch, store, {"canvas_flow": cfg})

    out = await o2.handle_message("s1", "sam@example.com")

    assert seen["config"] == cfg
    assert out["state"] == S.FINALIZE_CANVAS.value


@pytest.mark.asyncio
async def test_orchestrator_without_canvas_flow_is_unchanged(monkeypatch):
    """The control: an unconfigured store passes None and still asks purpose,
    so the wiring changes behaviour only when a store opts in."""
    store = _at_email_store(None)
    seen = _wire(monkeypatch, store, {})

    out = await o2.handle_message("s1", "sam@example.com")

    assert seen["config"] is None
    assert out["state"] == S.ASK_PURPOSE.value
