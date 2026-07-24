# Workstream D — Admin-Configurable Flow Sequence (V3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each store enable/disable and reorder a curated safe subset of v2 canvas steps (`quantity`, `needed_by`, `purpose`) via `stores.brand` config, read through a pure config-aware compose that the first-unmet router walks — with every dependency-locked step frozen in place.

**Architecture:** A per-store `brand.canvas_flow` blob (validated like `validate_brand`) declares an order + on/off flag for the three genuinely-independent configurable steps. A **pure** `effective_registry(config)` in `state_machine_v2.py` keeps every locked step at its exact registry index and redistributes only the configurable steps among the indices they already occupy — so no locked step ever moves and the compose is exhaustively unit-testable with plain dicts. `next_step(collected, config=None)` walks the composed list; a falsy config returns `cs.REGISTRY` byte-for-byte so the entire existing baseline is unchanged.

**Tech Stack:** Python 3.12, FastAPI, Supabase; React admin frontend

## Global Constraints
- CONDITIONAL workstream: low-complexity only. If the safe-subset compose entangles with dependency ordering, STOP and drop D.
- Only the safe subset (purpose, needed_by, quantity, decoration, anything_else) is reorderable/toggleable. Locked steps (name, intro, logo loop, email, prepare-steps, finalize) never move.
- Effective-step-list compose is a PURE function of (config, collected), unit-testable with plain dicts.
- Per-store config in `stores.brand` jsonb, validated server-side like validate_brand.
- Baseline `CANVAS_ORCHESTRATOR_V2=false pytest -q` stays green.

---

## File Structure

```
backend/app/services/conversation/canvas_steps.py        (edit) CONFIGURABLE_STEP_IDS export
backend/app/services/conversation/state_machine_v2.py    (edit) effective_registry() + next_step(config=)
backend/app/services/branding.py                         (edit) validate_canvas_flow() + validate_brand hook
backend/app/services/conversation/orchestrator_v2.py     (edit) read store config, thread into next_step
backend/tests/test_branding.py                           (edit) canvas_flow validation tests
backend/tests/test_state_machine_v2.py                   (edit) effective_registry + config-aware next_step tests
backend/tests/test_v2_e2e.py                             (edit) orchestrator threads store config
backend/tests/test_admin_store_branding.py               (edit) canvas_flow survives PATCH merge + GET
frontend/src/lib/types.ts                                (edit) Brand.canvas_flow field
frontend/src/admin/views/BrandingView.tsx                (edit) "Flow steps" card (toggle + reorder)
```

No migration is required: `stores.brand` is an existing jsonb column and `canvas_flow` is a new key inside it (same pattern as `canvas_intro`, added in the per-store-branding work with a comment-only migration).

---

## Complexity gate

**Read this before writing any code. This workstream was shipped as CONDITIONAL: build it only if the safe-subset compose stays trivial. It does — but only after narrowing the subset, which is documented here so a future reader knows the narrowing was deliberate, not an oversight.**

The spec's Workstream D lists the safe subset as `purpose, needed_by, quantity, decoration, anything_else`, **and in the very next paragraph lists `prepare`-bearing steps (decoration's store load) as dependency-LOCKED.** Those two statements conflict. Verifying against the real registry (`canvas_steps.py`) resolves the conflict decisively, and two of the five named steps must be excluded:

1. **`decoration` (`S.ASK_DECORATION`) is excluded — it is `prepare`-bearing.** Its record declares `prepare=_prepare_decoration`, which loads the store's decoration methods and *may satisfy its own step*; `orchestrator_v2` re-resolves `next_step` after running it. The spec's own locked-set rule names exactly this ("`prepare`-bearing steps (`decoration`'s store load)"). It stays frozen. Its conditional partner `S.ASK_DECORATION_MIX` (gated on `decoration_mix`) stays frozen with it.
2. **`anything_else` (`S.ASK_ANYTHING_ELSE`) is excluded — it is a decor-loop step, not an independent one.** It carries `_apply_anything_else` (which clears `decor_choice/decor_face/decor_placed/more_decor/decor_done` to re-open the loop) and its `done_when` reads `decor_done`. It is position-coupled to `ASK_ADD_DECOR → ASK_DECOR_PLACEMENT → DECOR_ADJUST`; reordering it out of that run breaks the "add another?" UX. It stays frozen.

The **genuinely-independent** subset that remains — and the one this plan implements — is:

| Step | `done_when` reads | `apply` | `prepare` | loop? | Safe? |
|---|---|---|---|---|---|
| `S.ASK_QUANTITY` | own `quantity` only | none | none | no | ✅ |
| `S.NEEDED_BY` (from Workstream B) | own `needed_by` only | none | none | no | ✅ |
| `S.ASK_PURPOSE` | own `purpose` only | none (has `direct_answer`) | none | no | ✅ |

These three are safe to reorder/disable because **no other step's `done_when` reads `quantity`, `needed_by`, or `purpose`** (verified: `ASK_EMAIL` reads `email_captured`; `ASK_DECORATION` reads `decoration_done`/`decoration_mix`; `FINALIZE_CANVAS` reads nothing). So moving or removing any of them cannot un-satisfy any other step, and the load-bearing invariant (no `FINALIZE_CANVAS` without `email_captured`, because `ASK_EMAIL` — locked — precedes finalize — locked) is untouched.

**The compose stays pure and trivial because of one design choice:** locked steps keep their exact registry index; the configurable steps are only ever redistributed among *the indices configurable steps already occupy*. Nothing crosses a locked step's position. This sidesteps the one real entanglement (the configurable steps are not contiguous in the registry — `ASK_QUANTITY` sits before `ASK_DECORATION`/`ASK_EMAIL`, `NEEDED_BY`/`ASK_PURPOSE` after them) without ever moving a locked step. If, while implementing Task 2, you find you need to move a locked step, splice a configurable step into a locked index, or add a per-step `done_when` dependency to make the compose work — **STOP and drop D from the batch.** That is the entanglement the gate exists to catch.

**Preconditions:**
- **Workstream B must be merged first** (it adds `S.NEEDED_BY` to the enum and the `needed_by` registry step). This plan sources the configurable set by string id from `REGISTRY`, so a not-yet-merged `needed_by` simply drops out of the set without an import error — but `needed_by` is only *configurable* once B ships it.

**Documented known gaps (minimal by design, not bugs):**
- The "Step X of N" progress counter (`_PROGRESS_PATH`) is left static; disabling a configurable step does not shrink the displayed total. Cosmetic; out of scope for the minimal build.
- When a configurable step is disabled, the remaining configurable steps pack into the earliest configurable indices (a disabled step frees the *last* configurable slot). This is deterministic and behaviourally safe (none of the three depend on ordering relative to locked steps); noted so the packing semantics are not mistaken for a bug.

---

## Task 1: Config schema + server-side validation

**Files:**
- `backend/app/services/conversation/canvas_steps.py` (edit — add `CONFIGURABLE_STEP_IDS` after `WRITABLE_SLOTS`, ~line 611)
- `backend/app/services/branding.py` (edit — add `_validate_canvas_flow`, hook into `validate_brand` ~line 60)
- Test: `backend/tests/test_branding.py` (edit)

**Interfaces:**
- Produces `canvas_steps.CONFIGURABLE_STEP_IDS: frozenset[str]` — the step-id strings an admin may reorder/disable (`{"ask_quantity", "needed_by", "ask_purpose"}` filtered to those actually present in `REGISTRY`).
- Produces `branding._validate_canvas_flow(raw) -> dict` and extends `branding.validate_brand(brand) -> dict` to validate a `canvas_flow` key when present.
- Config shape stored in `stores.brand`:
  ```json
  {"canvas_flow": {"steps": [
      {"id": "ask_purpose",  "enabled": false},
      {"id": "needed_by",    "enabled": true},
      {"id": "ask_quantity", "enabled": true}
  ]}}
  ```
  The list *order* is the relative step order; `enabled:false` disables. Ids not in the list keep default order + enabled.

### Steps

- [x] **Step 1: Write the failing validation tests.** Append to `backend/tests/test_branding.py`:

```python
def test_validate_brand_accepts_valid_canvas_flow():
    cleaned = branding.validate_brand({
        "canvas_flow": {"steps": [
            {"id": "ask_purpose", "enabled": False},
            {"id": "needed_by", "enabled": True},
            {"id": "ask_quantity", "enabled": True},
        ]}
    })
    assert cleaned["canvas_flow"]["steps"] == [
        {"id": "ask_purpose", "enabled": False},
        {"id": "needed_by", "enabled": True},
        {"id": "ask_quantity", "enabled": True},
    ]


def test_validate_brand_defaults_enabled_when_omitted():
    cleaned = branding.validate_brand({"canvas_flow": {"steps": [{"id": "ask_quantity"}]}})
    assert cleaned["canvas_flow"]["steps"] == [{"id": "ask_quantity", "enabled": True}]


def test_validate_brand_rejects_a_locked_step_id():
    # The guard that stops an admin ever disabling/reordering a locked step:
    # ask_email must precede finalize, so it is not in the configurable set.
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": {"steps": [{"id": "ask_email"}]}})


def test_validate_brand_rejects_an_unknown_step_id():
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": {"steps": [{"id": "not_a_step"}]}})


def test_validate_brand_rejects_duplicate_step_ids():
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": {"steps": [
            {"id": "ask_quantity"}, {"id": "ask_quantity"},
        ]}})


def test_validate_brand_rejects_non_bool_enabled():
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": {"steps": [{"id": "ask_quantity", "enabled": "yes"}]}})


def test_validate_brand_rejects_non_list_steps():
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": {"steps": "ask_quantity"}})


def test_validate_brand_without_canvas_flow_is_untouched():
    # Baseline invariant: a brand with no canvas_flow key comes back identical.
    cleaned = branding.validate_brand({"primary_colour": "#FF5C00"})
    assert "canvas_flow" not in cleaned
```

- [x] **Step 2: Run the tests — expect FAIL** (`_validate_canvas_flow` does not exist; the locked/unknown/duplicate cases pass through untouched today):

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_branding.py -q
```
Expected: the eight new tests FAIL (accepts-valid returns the raw dict unchanged with no `enabled` default; the four reject-cases do not raise).

- [x] **Step 3: Add `CONFIGURABLE_STEP_IDS` to `canvas_steps.py`.** Insert immediately after the `WRITABLE_SLOTS` block (after ~line 611, before `SLOT_ENUMS`):

```python
# --- V3 admin-configurable flow (Workstream D) --------------------------------
# The curated SAFE SUBSET: the only steps an admin may reorder/disable per store.
# Each is genuinely independent — its done_when reads only its OWN slot, it has
# no apply cross-effect, no prepare, and it belongs to no loop — so no other
# step's done_when can break when it moves or is dropped. Everything else is
# dependency-LOCKED and never moves: name, intro, the logo loop, the decor loop
# (incl. ASK_ANYTHING_ELSE), ASK_DECORATION (prepare-bearing) + ASK_DECORATION_MIX,
# ASK_EMAIL (must precede finalize), and FINALIZE_CANVAS. `needed_by` is added by
# Workstream B; sourcing the set from REGISTRY by id string means a not-yet-merged
# needed_by simply drops out rather than raising at import.
_CONFIGURABLE_STEP_NAMES: frozenset[str] = frozenset(
    {"ask_quantity", "needed_by", "ask_purpose"}
)
CONFIGURABLE_STEP_IDS: frozenset[str] = frozenset(
    s.id.value for s in REGISTRY if s.id.value in _CONFIGURABLE_STEP_NAMES
)
```

- [x] **Step 4: Add `_validate_canvas_flow` and the `validate_brand` hook in `branding.py`.** Add the helper above `validate_brand` (after `_validate_menu_items`, ~line 44):

```python
def _validate_canvas_flow(raw) -> dict:
    """Validate a per-store canvas flow config. The id allow-list IS the guard
    that keeps admins away from every dependency-locked step: only the curated
    safe subset (CONFIGURABLE_STEP_IDS) may be named, so a locked step can never
    be disabled or reordered. Import is function-local to avoid any module-load
    cycle (canvas_steps pulls in leads/intent_extractor)."""
    from app.services.conversation.canvas_steps import CONFIGURABLE_STEP_IDS

    if not isinstance(raw, dict):
        raise ValueError("canvas_flow must be an object")
    steps = raw.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("canvas_flow.steps must be a list")
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in steps:
        if not isinstance(item, dict):
            raise ValueError("each flow step must be an object")
        sid = item.get("id")
        if sid not in CONFIGURABLE_STEP_IDS:
            raise ValueError(f"step '{sid}' is not reorderable/optional")
        if sid in seen:
            raise ValueError(f"duplicate flow step '{sid}'")
        seen.add(sid)
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("flow step 'enabled' must be a boolean")
        cleaned.append({"id": sid, "enabled": enabled})
    return {"steps": cleaned}
```

Then hook it into `validate_brand`, immediately after the `menu_items` block and before the `canvas_intro` block (~line 60):

```python
    if "menu_items" in cleaned:
        cleaned["menu_items"] = _validate_menu_items(cleaned["menu_items"])
    if "canvas_flow" in cleaned:
        cleaned["canvas_flow"] = _validate_canvas_flow(cleaned["canvas_flow"])
    intro = cleaned.get("canvas_intro")
```

- [x] **Step 5: Run the tests — expect PASS:**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_branding.py -q
```
Expected: all tests PASS (existing branding tests + the eight new ones).

- [x] **Step 6: Commit.**

```bash
cd backend && git add app/services/conversation/canvas_steps.py app/services/branding.py tests/test_branding.py
git commit -m "$(cat <<'EOF'
feat(v3): canvas_flow config schema + server-side validation

Add CONFIGURABLE_STEP_IDS (the safe subset: quantity/needed_by/purpose)
and validate_brand hook for stores.brand.canvas_flow. The id allow-list
is the guard that keeps admins away from every dependency-locked step.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Pure compose function + config-aware next_step

**Files:**
- `backend/app/services/conversation/state_machine_v2.py` (edit — add `effective_registry`, extend `next_step` ~line 52)
- Test: `backend/tests/test_state_machine_v2.py` (edit)

**Interfaces:**
- Produces `state_machine_v2.effective_registry(config: dict | None) -> tuple[Step, ...]` — PURE (reads only `config` + `cs.REGISTRY`; no `collected`, no DB). Falsy config returns `cs.REGISTRY` unchanged.
- Extends `state_machine_v2.next_step(collected: dict, config: dict | None = None) -> Step` — default `None` keeps every existing caller and test byte-identical.
- Consumes `canvas_steps.REGISTRY`, `canvas_steps.CONFIGURABLE_STEP_IDS`, `canvas_steps.Step`.

### Steps

- [x] **Step 1: Write the failing compose tests** using plain dicts. Append to `backend/tests/test_state_machine_v2.py`:

```python
# --- Workstream D: config-aware compose (pure, plain dicts) --------------------

def _flow(*pairs):
    """A canvas_flow config from (id, enabled) pairs."""
    return {"steps": [{"id": i, "enabled": e} for i, e in pairs]}


def test_effective_registry_is_identity_without_config():
    assert v2.effective_registry(None) is cs.REGISTRY
    assert v2.effective_registry({}) is cs.REGISTRY
    assert v2.effective_registry({"steps": []}) == cs.REGISTRY


def test_effective_registry_keeps_every_locked_step_in_place():
    # Reorder the configurable subset; every non-configurable step must keep its
    # exact relative position. Nothing crosses a locked step.
    eff = v2.effective_registry(_flow(("ask_purpose", True), ("ask_quantity", True)))
    locked_before = [s.id for s in cs.REGISTRY if s.id.value not in cs.CONFIGURABLE_STEP_IDS]
    locked_after = [s.id for s in eff if s.id.value not in cs.CONFIGURABLE_STEP_IDS]
    assert locked_after == locked_before


def test_effective_registry_reorders_only_the_configurable_slots():
    # ask_quantity naturally sits at an earlier index than ask_purpose. Asking
    # for purpose first must put purpose in the earliest configurable slot and
    # quantity in a later one — without moving any locked step.
    eff = v2.effective_registry(_flow(("ask_purpose", True), ("ask_quantity", True)))
    order = [s.id.value for s in eff if s.id.value in cs.CONFIGURABLE_STEP_IDS]
    assert order.index("ask_purpose") < order.index("ask_quantity")


def test_effective_registry_drops_a_disabled_step():
    eff = v2.effective_registry(_flow(("ask_purpose", False)))
    ids = [s.id.value for s in eff]
    assert "ask_purpose" not in ids
    assert "ask_quantity" in ids            # untouched configurable steps remain
    # exactly one step removed
    assert len(eff) == len(cs.REGISTRY) - 1


def test_effective_registry_ignores_unmentioned_configurable_steps():
    # Only ask_purpose is named; quantity/needed_by keep default order + enabled.
    eff = v2.effective_registry(_flow(("ask_purpose", True)))
    assert {s.id.value for s in eff} == {s.id.value for s in cs.REGISTRY}


def test_next_step_default_matches_the_bare_registry_walk():
    # The baseline guarantee: next_step(collected) with no config is unchanged.
    c = {"flow_mode": "canvas"}
    from tests.canvas_step_helpers import satisfy
    for step in cs.REGISTRY:
        assert v2.next_step(c).id is step.id
        assert v2.next_step(c, None).id is step.id
        satisfy(c, step)


def test_next_step_honours_a_reordering_config():
    # With purpose-before-quantity, a session that has answered everything up to
    # the first configurable slot is asked purpose, not quantity.
    cfg = _flow(("ask_purpose", True), ("ask_quantity", True))
    c = {"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
         "logos_done": True, "pending_logo": None, "decor_done": True}
    # first configurable step in the composed order is ask_purpose
    assert v2.next_step(c, cfg).id is S.ASK_PURPOSE


def test_next_step_skips_a_disabled_step():
    cfg = _flow(("ask_purpose", False))
    # Everything answered except purpose; purpose disabled -> finalize (given
    # email captured). Locked steps still gate normally.
    c = {"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
         "logos_done": True, "pending_logo": None, "decor_done": True,
         "quantity": 12, "decoration_done": True, "email_captured": True}
    assert v2.next_step(c, cfg).id is S.FINALIZE_CANVAS


def test_next_step_still_blocks_finalize_without_email_under_config():
    # The load-bearing invariant survives reordering: email is locked before
    # finalize, so no config can reach finalize without email_captured.
    cfg = _flow(("ask_purpose", True), ("ask_quantity", True))
    c = {"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
         "logos_done": True, "pending_logo": None, "decor_done": True,
         "quantity": 12, "decoration_done": True, "purpose": "team caps"}
    assert v2.next_step(c, cfg).id is S.ASK_EMAIL
```

- [x] **Step 2: Run the tests — expect FAIL** (`effective_registry` does not exist; `next_step` takes one arg):

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_state_machine_v2.py -q
```
Expected: the new tests error/FAIL (`AttributeError: module ... has no attribute 'effective_registry'`, `TypeError: next_step() takes 1 positional argument but 2 were given`).

- [x] **Step 3: Implement `effective_registry` and extend `next_step`** in `state_machine_v2.py`. Replace the existing `next_step` (lines 52–58) with:

```python
def effective_registry(config: dict | None) -> tuple[Step, ...]:
    """The registry as reordered/filtered by a store's canvas_flow config.

    PURE: a function of (config, cs.REGISTRY) only — no collected, no DB, no LLM.
    Locked steps keep their EXACT registry index; the configurable steps are
    redistributed among the indices configurable steps already occupy, in the
    admin's order, with disabled ones dropped (trailing configurable slots
    collapse). Nothing crosses a locked step's position — that is what keeps this
    trivial and is the invariant the Complexity gate protects. A falsy/absent
    config returns cs.REGISTRY unchanged, so every existing caller and the whole
    baseline are byte-identical.
    """
    registry = cs.REGISTRY
    if not config:
        return registry
    steps_cfg = config.get("steps") or []
    cfg_ids = cs.CONFIGURABLE_STEP_IDS

    disabled: set[str] = set()
    ordered: list[str] = []
    seen: set[str] = set()
    for item in steps_cfg:
        sid = (item or {}).get("id")
        if sid not in cfg_ids or sid in seen:
            continue
        seen.add(sid)
        if item.get("enabled") is False:
            disabled.add(sid)
        else:
            ordered.append(sid)
    # Configurable steps the admin never mentioned keep default (registry) order,
    # enabled, appended after the ones they did.
    for step in registry:
        sid = step.id.value
        if sid in cfg_ids and sid not in seen:
            ordered.append(sid)

    by_id = {s.id.value: s for s in registry if s.id.value in cfg_ids}
    present = [by_id[sid] for sid in ordered if sid in by_id]

    slots = [i for i, s in enumerate(registry) if s.id.value in cfg_ids]
    result: list[Step | None] = list(registry)
    for i in slots:
        result[i] = None
    for pos, step in zip(slots, present):
        result[pos] = step
    return tuple(s for s in result if s is not None)


def next_step(collected: dict, config: dict | None = None) -> Step:
    """The first step whose done_when is False, over the config-composed registry.
    FINALIZE_CANVAS is terminal (done_when always False) and always locked-last,
    so this always returns a Step."""
    for step in effective_registry(config):
        if not step.done_when(collected):
            return step
    return cs.REGISTRY[-1]
```

- [x] **Step 4: Run the tests — expect PASS:**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_state_machine_v2.py -q
```
Expected: all tests PASS, including the pre-existing `test_router_walks_every_step_in_declared_order` and `test_finalize_unreachable_without_email_captured` (proving the default path is byte-identical).

- [x] **Step 5: Commit.**

```bash
cd backend && git add app/services/conversation/state_machine_v2.py tests/test_state_machine_v2.py
git commit -m "$(cat <<'EOF'
feat(v3): pure effective_registry compose + config-aware next_step

Locked steps keep their exact registry index; the safe subset is
redistributed among its own slots per store config. Falsy config returns
REGISTRY unchanged so the baseline is byte-identical.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Wire the store config into the orchestrator

**Files:**
- `backend/app/services/conversation/orchestrator_v2.py` (edit — read `brand.canvas_flow`, thread into both `next_step` calls, ~lines 45–110)
- Test: `backend/tests/test_v2_e2e.py` (edit — reuse the `_FakeSB` harness)

**Interfaces:**
- Consumes `store["brand"]["canvas_flow"]` (already loaded via `get_store`).
- Produces: `orchestrator_v2.handle_message` passes the store's `canvas_flow` config to `v2.next_step(collected, flow_config)` at both the initial resolve and the post-`prepare` re-resolve.

### Steps

- [x] **Step 1: Write the failing orchestrator test.** Append to `backend/tests/test_v2_e2e.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_threads_store_canvas_flow_config(monkeypatch):
    """With a store config that disables ask_purpose, a session that has answered
    every step up to purpose (email captured) must route straight to
    FINALIZE_CANVAS, not ask the disabled purpose step."""
    store_row = {"session": {
        "id": "s1",
        "state": S.ASK_EMAIL.value,
        "store_id": "store-1",
        "collected": {"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
                      "logos_done": True, "pending_logo": None, "decor_done": True,
                      "quantity": 12, "decoration_done": True,
                      "decoration_options": ["Embroidery"]},
        "upsell_count": 0,
    }}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store_row))
    monkeypatch.setattr(o2, "get_store", lambda _id: {
        "id": "store-1", "persona_name": "Ricardo",
        "brand": {"canvas_flow": {"steps": [{"id": "ask_purpose", "enabled": False}]}},
    })
    # Capture the config next_step actually receives.
    seen: dict = {}
    real_next = v2.next_step
    monkeypatch.setattr(o2.v2, "next_step",
                        lambda collected, config=None: (seen.update(config=config) or real_next(collected, config)))
    # Verify the email so _apply_email marks email_captured.
    monkeypatch.setattr(o2.leads_service if hasattr(o2, "leads_service") else cs.leads_service,
                        "capture_lead_and_verify", lambda s, c, e: ("lead-1", True))

    out = await o2.handle_message("s1", "sam@example.com")

    assert seen["config"] == {"steps": [{"id": "ask_purpose", "enabled": False}]}
    # purpose disabled -> next resting state is the finalize handoff, not ask_purpose
    assert out["state"] in (S.FINALIZE_CANVAS.value, S.QUOTE_REQUESTED.value)
    assert out["state"] != S.ASK_PURPOSE.value
```

> Note: `cs.leads_service` is the `leads as leads_service` import inside `canvas_steps`; `_apply_email` calls it. If the monkeypatch target differs in the real tree, patch `app.services.leads.capture_lead_and_verify` directly.

- [x] **Step 2: Run the test — expect FAIL** (orchestrator does not read `canvas_flow`; `next_step` is called with only `collected`, so `seen["config"]` is `None` and purpose is asked):

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_v2_e2e.py::test_orchestrator_threads_store_canvas_flow_config -q
```
Expected: FAIL (`seen["config"]` is `None`, and/or state is `ask_purpose`).

- [x] **Step 3: Thread the config through `orchestrator_v2.handle_message`.** After the `intro = canvas_intro_text(store)` line (~line 49), add:

```python
    flow_config = ((store or {}).get("brand") or {}).get("canvas_flow")
```

Then change the initial resolve (~line 102) from:

```python
    next_ = v2.next_step(collected)
    if next_.prepare:
        next_.prepare(collected, store)
        next_ = v2.next_step(collected)
```

to:

```python
    next_ = v2.next_step(collected, flow_config)
    if next_.prepare:
        # prepare may satisfy its own step (a store with no decoration methods),
        # so re-resolve under the same config.
        next_.prepare(collected, store)
        next_ = v2.next_step(collected, flow_config)
```

- [x] **Step 4: Run the test — expect PASS:**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_v2_e2e.py -q
```
Expected: all `test_v2_e2e.py` tests PASS (the full chip-label walk still passes — it uses no store config, so `flow_config` is `None` and routing is unchanged).

- [x] **Step 5: Commit.**

```bash
cd backend && git add app/services/conversation/orchestrator_v2.py tests/test_v2_e2e.py
git commit -m "$(cat <<'EOF'
feat(v3): orchestrator_v2 threads store canvas_flow into next_step

Reads store.brand.canvas_flow and passes it to both next_step calls
(initial resolve + post-prepare re-resolve). No config -> unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Admin GET/PATCH persistence

**Files:**
- `backend/app/api/routes/admin_stores.py` (no change expected — PATCH already routes `body.brand` through `validate_brand` and merges; GET already returns the full `brand`)
- Test: `backend/tests/test_admin_store_branding.py` (edit — prove `canvas_flow` survives the read-merge PATCH and comes back on GET)

**Interfaces:**
- Consumes `PATCH /admin/stores/{id}` with `{"brand": {"canvas_flow": {...}}}`; the existing merge-not-clobber (`{**existing_brand, **validated}`) preserves `logo_url`/`canvas_intro`/`menu_items` alongside `canvas_flow`.
- Produces: `canvas_flow` stored in `stores.brand`, returned by `GET /admin/stores/{id}`.

### Steps

- [ ] **Step 1: Write the failing persistence tests.** Append to `backend/tests/test_admin_store_branding.py`:

```python
def test_patch_accepts_and_merges_canvas_flow(monkeypatch):
    """A canvas_flow PATCH must validate, and must merge without wiping the
    existing logo_url (same read-merge guarantee as colours)."""
    app.dependency_overrides[require_admin] = lambda: None
    row = {"id": "s1", "slug": "acme", "name": "Acme",
           "brand": {"logo_url": "uploads/x.png", "primary_colour": "#111"}}
    fake = _FakeTable(row)
    monkeypatch.setattr(
        "app.api.routes.admin_stores.get_supabase",
        lambda: type("SB", (), {"table": lambda self, name: fake})(),
    )
    client = TestClient(app)
    try:
        r = client.patch(
            "/admin/stores/s1",
            json={"brand": {"canvas_flow": {"steps": [
                {"id": "ask_purpose", "enabled": False},
                {"id": "ask_quantity", "enabled": True},
            ]}}},
            headers={"X-Admin-Secret": "z"},
        )
        assert r.status_code == 200
        brand = r.json()["brand"]
        assert brand["canvas_flow"]["steps"] == [
            {"id": "ask_purpose", "enabled": False},
            {"id": "ask_quantity", "enabled": True},
        ]
        assert brand["logo_url"] == "uploads/x.png"      # merge, not clobber
        assert brand["primary_colour"] == "#111"
    finally:
        app.dependency_overrides.clear()


def test_patch_rejects_a_locked_step_in_canvas_flow(client):
    r = client.patch(
        "/admin/stores/s1",
        json={"brand": {"canvas_flow": {"steps": [{"id": "ask_email"}]}}},
        headers={"X-Admin-Secret": "z"},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Run the tests — expect PASS immediately** (no route change: `validate_brand` from Task 1 already validates `canvas_flow`, and the merge is already read-merge). This task's TDD is a *verification* that the existing route composes correctly with Task 1:

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_admin_store_branding.py -q
```
Expected: all tests PASS. **If `test_patch_rejects_a_locked_step_in_canvas_flow` does NOT return 400**, Task 1's validator hook is not wired — return to Task 1 Step 4 before proceeding.

- [ ] **Step 3: Commit.**

```bash
cd backend && git add tests/test_admin_store_branding.py
git commit -m "$(cat <<'EOF'
test(v3): canvas_flow survives PATCH read-merge and rejects locked ids

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Full backend baseline gate.**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest -q
```
Expected: green (the documented 788+ passing baseline, now +new). If anything unrelated flips, STOP and investigate before the frontend task.

---

## Task 5: Admin frontend editor ("Flow steps" card)

**Files:**
- `frontend/src/lib/types.ts` (edit — add `canvas_flow` to `Brand`, ~line 112)
- `frontend/src/admin/views/BrandingView.tsx` (edit — add a "Flow steps" card between the Canvas-intro card and the Menu card, ~line 150)
- Test: none new required (the store-level backend guard is the source of truth; the frontend mirrors it). Reuse the existing Windows-stall-safe `BrandingView` vitest if present.

**Interfaces:**
- Consumes `Brand.canvas_flow?: { steps: { id: string; enabled: boolean }[] }`.
- Produces: a toggle + up/down reorder UI over the three configurable steps, persisted through the existing `updateStoreBrand` (which strips `logo_url` and PATCHes the whole brand, so `canvas_flow` flows through untouched).

### Steps

- [ ] **Step 1: Add `canvas_flow` to the `Brand` interface** in `frontend/src/lib/types.ts` (replace the interface body ~lines 112–119):

```ts
/** One configurable step in the v2 canvas flow (V3 admin ordering). */
export interface FlowStep {
  id: string
  enabled: boolean
}

/** Per-store brand config (GET /storefront). All fields optional — unset fields
 *  keep the current MadHats Tailwind fallbacks. */
export interface Brand {
  logo_url?: string
  primary_colour?: string
  header_bg?: string
  header_text?: string
  menu_items?: MenuItem[]
  canvas_intro?: string
  canvas_flow?: { steps: FlowStep[] }
}
```

- [ ] **Step 2: Add the "Flow steps" card to `BrandingView.tsx`.** First add a label map + helpers near the top of the component body (after `const menu = brand.menu_items ?? []`, ~line 51):

```tsx
  // The safe, admin-configurable subset (mirrors backend CONFIGURABLE_STEP_IDS).
  // Every other step is dependency-locked and never surfaced here.
  const FLOW_STEPS: { id: string; label: string }[] = [
    { id: 'ask_quantity', label: 'How many caps?' },
    { id: 'needed_by', label: 'When do you need it by?' },
    { id: 'ask_purpose', label: 'What is the hat for?' },
  ]
  // Compose the current view: config order first, then any unmentioned defaults.
  const configured = brand.canvas_flow?.steps ?? []
  const flow = [
    ...configured.filter(s => FLOW_STEPS.some(f => f.id === s.id)),
    ...FLOW_STEPS.filter(f => !configured.some(s => s.id === f.id))
                 .map(f => ({ id: f.id, enabled: true })),
  ]
  const labelOf = (id: string) => FLOW_STEPS.find(f => f.id === id)?.label ?? id
  function setFlow(steps: FlowStep[]) {
    setBrand(b => ({ ...b, canvas_flow: { steps } })); setSaved(false)
  }
  function toggleStep(i: number) {
    setFlow(flow.map((s, j) => j === i ? { ...s, enabled: !s.enabled } : s))
  }
  function moveStep(i: number, dir: -1 | 1) {
    const j = i + dir
    if (j < 0 || j >= flow.length) return
    const next = [...flow];[next[i], next[j]] = [next[j], next[i]]; setFlow(next)
  }
```

`FlowStep` must be imported — extend the existing type import at the top of the file:

```tsx
import type { Brand, MenuItem, FlowStep } from '../../lib/types'
```

Then insert the card JSX between the Canvas-intro `</label>` and the Menu `<div>` (~line 150):

```tsx
      {/* Flow steps (V3 — reorder/disable the safe subset) */}
      <div className="flex flex-col gap-2 rounded-xl border border-[#e0e1ea] bg-white p-4">
        <span className="text-[13px] font-medium">Flow steps</span>
        <span className="text-[12px] text-[#9a9ab0]">
          Reorder or switch off these questions. Everything else in the flow is fixed.
        </span>
        {flow.map((s, i) => (
          <div key={s.id} className="flex items-center gap-2">
            <label className="flex flex-1 items-center gap-2 text-[13px]">
              <input type="checkbox" checked={s.enabled}
                     onChange={() => toggleStep(i)}
                     aria-label={`${labelOf(s.id)} enabled`} />
              <span className={s.enabled ? '' : 'text-[#9a9ab0] line-through'}>{labelOf(s.id)}</span>
            </label>
            <button onClick={() => moveStep(i, -1)} disabled={i === 0}
                    aria-label={`Move ${labelOf(s.id)} up`}
                    className="rounded border border-[#e0e1ea] px-2 text-[12px] disabled:opacity-40">↑</button>
            <button onClick={() => moveStep(i, 1)} disabled={i === flow.length - 1}
                    aria-label={`Move ${labelOf(s.id)} down`}
                    className="rounded border border-[#e0e1ea] px-2 text-[12px] disabled:opacity-40">↓</button>
          </div>
        ))}
      </div>
```

The existing `onSave` already PATCHes `rest` (the whole brand minus `logo_url`), so `canvas_flow` is persisted with no `onSave` change. No frontend `validate()` change is needed (only known step ids and booleans are ever produced by this UI; the server re-validates regardless).

- [ ] **Step 3: Verify the frontend builds and the targeted admin test (if present) passes.**

```bash
cd frontend && npm run build
cd frontend && npx vitest run src/admin/views/BrandingView.test.tsx
```
Expected: build succeeds; the existing `BrandingView` test (if any) still passes. (Full `vitest run` is a known Windows tinypool flake — keep it targeted.)

- [ ] **Step 4: Commit.**

```bash
cd frontend && git add src/lib/types.ts src/admin/views/BrandingView.tsx
git commit -m "$(cat <<'EOF'
feat(v3): admin Branding "Flow steps" card — toggle + reorder safe subset

Reorder/disable quantity/needed-by/purpose per store; persisted into
brand.canvas_flow via the existing updateStoreBrand PATCH. Locked steps
are never surfaced.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Backend baseline green:**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest -q
```
Expected: all pass (baseline + new tests across `test_branding.py`, `test_state_machine_v2.py`, `test_v2_e2e.py`, `test_admin_store_branding.py`).

- [ ] **Confirm the invariants held throughout (grep sanity):** no locked-step id appears in `CONFIGURABLE_STEP_IDS`; `effective_registry(None) is cs.REGISTRY`; `next_step`'s default arg is `None`. All are asserted by tests above; if any test was skipped, do not claim completion.

- [ ] **Report to orchestrator:** what shipped (config schema + pure compose + orchestrator wiring + admin editor), the narrowed subset decision from the Complexity gate (decoration + anything_else excluded as prepare-bearing / loop-coupled), the documented known gaps (static progress counter; disabled-step slot-packing), and the Workstream B precondition (`needed_by` must be merged for it to be configurable).
