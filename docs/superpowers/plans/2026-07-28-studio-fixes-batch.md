# Studio Fixes Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five independent fixes to the canvas Design Studio and quote pipeline — make the text-element field findable, handle obscene language, correct a false copy claim, stop the Adjust panel crowding the cap, and surface the background-removal flag to admin/sales.

**Architecture:** Additive and layered. One new pure backend module (`profanity.py`) with no I/O, consumed at two call sites with opposite policies (lenient in chat, strict at finalize). One new frontend hook (`useIsDesktop`) that picks which column mounts an existing component. Everything else is edits to existing files. No migrations, no new dependencies, no schema changes.

**Tech Stack:** Python 3.12 / FastAPI / pytest (backend); React 18 / TypeScript / Zustand / Tailwind / vitest + @testing-library (frontend).

**Spec:** `docs/superpowers/specs/2026-07-28-studio-fixes-batch-design.md`

## Global Constraints

- **No PII in logs** (security rule 10). Profanity logging records the matched term ONLY — never customer name, email, or message.
- **Profanity matching is word-boundary only, never substring.** `state_machine.is_negative` matching `no` inside `another` is a documented live landmine; a substring list is the Scunthorpe version of it.
- **`profanity.py` is pure** — no LLM, no network, no DB. It must never be able to stall a turn.
- **Every admin surface reads `collected["elements"][].remove_bg`** — the same field the render reads. Never `collected["logos"][].bg` (the chip answer), which is documented as divergent.
- **Do not add `h-full` or `flex-1` to the ToolRail root** (`ToolRail.tsx:64`). `mt-auto` on the Done button is inert by design; making the rail fill its column pushes the Adjust panel off-screen.
- **v1 `orchestrator.py` is not modified.** It is the retained backup path.
- **Feature-detect `matchMedia` and observers.** jsdom ships neither; constructing one unconditionally throws through every test that mounts `Surface`.
- Backend tests run with `CANVAS_ORCHESTRATOR_V2=false` unless a task says otherwise (the repo-root `.env` default of `true` flips 3 unrelated tests red).
- Backend test command: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`
- Frontend test command: `cd frontend && npx vitest run <path>`
- Commit after every task. End commit messages with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## File Structure

**Create:**
- `backend/app/services/profanity.py` — pure severity scanner (word lists + `scan` + `find_terms`)
- `backend/tests/test_profanity.py` — scanner unit tests
- `frontend/src/lib/useIsDesktop.ts` — feature-detected `md`-breakpoint hook
- `frontend/src/__tests__/selectedToolbarText.test.tsx` — text-field tests
- `frontend/src/__tests__/adjustPanelPlacement.test.tsx` — panel placement tests

**Modify:**
- `backend/app/api/routes/sessions.py` — copy fix; cap-side profanity gate
- `backend/app/services/conversation/orchestrator_v2.py` — chat-side lenient guard
- `backend/app/prompts.py` — decline copy; sales email breakdown slot
- `backend/app/services/design_summary.py` — `design_breakdown()` helper
- `backend/app/services/components.py` — `assetPath` fix + remove-bg labels
- `backend/app/services/email.py` — fill the breakdown slot
- `backend/app/api/routes/admin_leads.py` — per-element summary on quote rows
- `frontend/src/store/canvasStore.ts` — export `TEXT_PLACEHOLDER`
- `frontend/src/components/DesignStudio/SelectedToolbar.tsx` — text field + `variant` prop
- `frontend/src/components/DesignStudio/Surface.tsx` — placeholder const + panel placement
- `frontend/src/admin/adminApi.ts` — `QuoteElement` type
- `frontend/src/admin/views/QuoteRequestsView.tsx` — remove-bg badge
- `frontend/src/admin/views/SessionDetailView.tsx` — rebind remove-bg row

---

### Task 1: Quote-confirmation copy fix

**Files:**
- Modify: `backend/app/api/routes/sessions.py:279-284`
- Test: `backend/tests/test_canvas_routes.py`

**Interfaces:**
- Consumes: nothing
- Produces: nothing

The trailing clause is false. In v2 the `AWAIT_EMAIL_VERIFY` hard gate means the address is already confirmed before `REQUEST_QUOTE`, so `finalize_canvas` cannot be reached with an unconfirmed address.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_canvas_routes.py`, immediately after
`test_v2_finalize_is_quote_gated_and_never_generates` (which ends near line 330).
It asserts on the actual response body — the fixtures and setup below are copied
from that test, which already drives this exact code path.

```python
def test_quote_reply_does_not_claim_the_email_is_unconfirmed(
        client, seeded_store_headers, canvas_session_id, monkeypatch):
    """v2 cannot reach finalize with an unconfirmed address — AWAIT_EMAIL_VERIFY
    gates it — so promising delivery 'once you confirm' is false."""
    monkeypatch.setattr("app.api.routes.sessions.settings.canvas_orchestrator_v2", True)
    row = client._fake.design_sessions.rows[canvas_session_id]
    row["collected"] = {**(row.get("collected") or {}),
                        "quote_requested": True, "reference_code": "MH-BCDFGH"}

    design = {"colourway": None,
              "faces": {"front": [{"id": "e1", "type": "text", "content": "HI",
                                   "x": 0.5, "y": 0.4, "width": 0.2, "height": 0.1,
                                   "rotation": 0, "zIndex": 0}],
                        "back": [], "left": [], "right": []}}
    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": design}, headers=seeded_store_headers)

    assert r.status_code == 200
    reply = r.json()["reply"]
    assert "once you confirm" not in reply.lower()
    assert "We've also emailed it to you." in reply
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_canvas_routes.py::test_quote_reply_does_not_claim_the_email_is_unconfirmed -v`
Expected: FAIL — `assert "once you confirm your address" not in src`

- [ ] **Step 3: Apply the copy fix**

In `backend/app/api/routes/sessions.py`, replace:

```python
            reply = (
                f"All done — your request is in! Your reference is {reference}. "
                "Our team will be in touch with a quote soon. We've also emailed "
                "it to you once you confirm your address."
            )
```

with:

```python
            reply = (
                f"All done — your request is in! Your reference is {reference}. "
                "Our team will be in touch with a quote soon. We've also emailed "
                "it to you."
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_canvas_routes.py -q`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/sessions.py backend/tests/test_canvas_routes.py
git commit -m "fix(canvas-v2): drop the false 'once you confirm' clause from the quote reply

AWAIT_EMAIL_VERIFY already gates the flow, so the address is confirmed
before finalize_canvas can run.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Prominent text-element content field

**Files:**
- Modify: `frontend/src/store/canvasStore.ts` (add exported const near line 14)
- Modify: `frontend/src/components/DesignStudio/Surface.tsx:110`, `:325`
- Modify: `frontend/src/components/DesignStudio/SelectedToolbar.tsx:112-143`
- Test: `frontend/src/__tests__/selectedToolbarText.test.tsx` (create)

**Interfaces:**
- Consumes: `useCanvasStore` (existing), `CanvasElement` (existing)
- Produces: `TEXT_PLACEHOLDER: string` exported from `frontend/src/store/canvasStore.ts` — the literal a freshly added text element carries. Task 6 does not depend on it.

**Context:** `SelectedToolbar.tsx:114-115` renders the content input as `w-28 text-xs` with only an `aria-label` — no visible label — inline among the font dropdown and two sliders. `addText` (`canvasStore.ts:113-120`) already sets `selectedId: el.id`, so a newly added element is selected and the panel is mounted.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/__tests__/selectedToolbarText.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SelectedToolbar } from '../components/DesignStudio/SelectedToolbar'
import { useCanvasStore, TEXT_PLACEHOLDER } from '../store/canvasStore'

function reset() {
  useCanvasStore.setState({
    faces: { front: [], back: [], left: [], right: [] },
    activeFace: 'front',
    selectedId: null,
  })
}

describe('text element content field', () => {
  beforeEach(reset)

  it('renders a visible label, not just an aria-label', () => {
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
    render(<SelectedToolbar />)
    expect(screen.getByText('Your text')).toBeInTheDocument()
  })

  it('is full width rather than the old w-28', () => {
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
    render(<SelectedToolbar />)
    const input = screen.getByLabelText('Text content')
    expect(input.className).toContain('w-full')
    expect(input.className).not.toContain('w-28')
  })

  it('focuses and selects a freshly added element so typing replaces the placeholder', () => {
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
    render(<SelectedToolbar />)
    const input = screen.getByLabelText('Text content') as HTMLInputElement
    expect(document.activeElement).toBe(input)
    expect(input.selectionStart).toBe(0)
    expect(input.selectionEnd).toBe(TEXT_PLACEHOLDER.length)
  })

  it('does NOT steal focus for an element that has already been edited', () => {
    useCanvasStore.getState().addText('MADHATS')
    render(<SelectedToolbar />)
    const input = screen.getByLabelText('Text content')
    expect(document.activeElement).not.toBe(input)
  })

  it('still writes content through the store', async () => {
    useCanvasStore.getState().addText('MADHATS')
    render(<SelectedToolbar />)
    const input = screen.getByLabelText('Text content')
    await userEvent.clear(input)
    await userEvent.type(input, 'CREW')
    expect(useCanvasStore.getState().faces.front[0].content).toBe('CREW')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/__tests__/selectedToolbarText.test.tsx`
Expected: FAIL — `TEXT_PLACEHOLDER` is not exported from `canvasStore`

- [ ] **Step 3: Export the placeholder constant**

In `frontend/src/store/canvasStore.ts`, add after the `LINE_SHAPES` export (line 14):

```ts
/** The literal a freshly added text element carries. Exported because
 *  SelectedToolbar's autofocus guard compares against it — as two separate
 *  string literals they drift, and the guard then silently fails open to
 *  "never autofocus", which no test would catch. */
export const TEXT_PLACEHOLDER = 'Your text'
```

- [ ] **Step 4: Route both add-text call sites through the constant**

In `frontend/src/components/DesignStudio/Surface.tsx`, add `TEXT_PLACEHOLDER` to
the existing `canvasStore` import, then replace both literals:

Line 110: `if (canvasDirective?.autoOpen === 'text') addText('Your text')`
→ `if (canvasDirective?.autoOpen === 'text') addText(TEXT_PLACEHOLDER)`

Line 325: `<ToolRail onAddText={() => addText('Your text')} …`
→ `<ToolRail onAddText={() => addText(TEXT_PLACEHOLDER)} …`

- [ ] **Step 5: Add the guarded autofocus effect**

In `frontend/src/components/DesignStudio/SelectedToolbar.tsx`:

Extend the import on line 2 to `import { useCanvasStore, LINE_SHAPES, TEXT_PLACEHOLDER } from '../../store/canvasStore'`.

Add the ref beside `rootRef` (line 49):

```tsx
  const contentRef = useRef<HTMLInputElement>(null)
```

Add this effect immediately after the existing measuring effect (after line 67),
i.e. still ABOVE the `if (!el) return null` early return — hooks may not sit
after it:

```tsx
  // Focus+select ONLY while the content is still the untouched placeholder, so
  // a freshly added element can be typed straight over. Re-selecting an element
  // the customer already edited must not steal focus — on a phone that pops the
  // keyboard over the canvas. Keyed on the id alone: the guard goes false on the
  // first keystroke, so re-running per character would be pointless churn.
  useEffect(() => {
    if (el?.type !== 'text' || el.content !== TEXT_PLACEHOLDER) return
    contentRef.current?.focus()
    contentRef.current?.select()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [el?.id])
```

- [ ] **Step 6: Restructure the text branch**

In `frontend/src/components/DesignStudio/SelectedToolbar.tsx`, replace the whole
`{el.type === 'text' && (…)}` block (lines 112-143) with:

```tsx
      {el.type === 'text' && (
        <>
          {/* The content field is the point of a text element, so it gets its
              own full-width labelled row above the styling controls. It used to
              be a 112px unlabelled box wedged between the font dropdown and the
              sliders, which customers did not find. `basis-full` makes it claim
              a whole line of the wrapping flex row. */}
          <label className="basis-full flex flex-col gap-0.5">
            <span className="text-[10px] uppercase tracking-wide text-textMuted leading-none">Your text</span>
            <input ref={contentRef} value={el.content ?? ''}
              onChange={e => update(el.id, { content: e.target.value })}
              className="w-full bg-base border border-accent rounded px-2 py-1 text-sm text-textPrimary focus:outline-none focus:ring-2 focus:ring-accent/40"
              aria-label="Text content" />
          </label>
          <select value={el.font ?? 'Arial'} onChange={e => update(el.id, { font: e.target.value })}
            className="bg-base border border-border rounded px-1.5 py-0.5 text-xs max-w-[7rem]" aria-label="Font"
            style={{ fontFamily: el.font ?? 'Arial' }}>
            <optgroup label="Standard">
              {WEB_SAFE_FONTS.map(f => (
                <option key={f.family} value={f.family} style={{ fontFamily: f.family }}>{f.label}</option>
              ))}
            </optgroup>
            <optgroup label="Google Fonts">
              {GOOGLE_FONTS.map(f => (
                <option key={f.family} value={f.family} style={{ fontFamily: f.family }}>{f.label}</option>
              ))}
            </optgroup>
          </select>
          <input type="color" value={el.colour ?? '#ffffff'} onChange={e => update(el.id, { colour: e.target.value })}
            className="w-6 h-6 p-0 border-0 bg-transparent" aria-label="Text colour" />
          <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Font size">
            <span aria-hidden="true">A</span>
            <input type="range" className="w-20" min={12} max={96} value={el.fontSize ?? 36}
              onChange={e => update(el.id, { fontSize: Number(e.target.value) })} aria-label="Font size" />
          </label>
          <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Curve the text">
            <span aria-hidden="true">Curve</span>
            <input type="range" className="w-20" min={-100} max={100} step={5} value={el.curve ?? 0}
              onChange={e => update(el.id, { curve: Number(e.target.value) })} aria-label="Curve text" />
          </label>
        </>
      )}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/__tests__/selectedToolbarText.test.tsx`
Expected: PASS (5 tests)

- [ ] **Step 8: Check for regressions in neighbouring suites**

Run: `cd frontend && npx vitest run src/__tests__/surfaceDirective.test.tsx src/__tests__/ToolRail.test.tsx`
Expected: PASS. If a test asserted the old `'Your text'` literal, update it to import `TEXT_PLACEHOLDER`.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/store/canvasStore.ts frontend/src/components/DesignStudio/SelectedToolbar.tsx frontend/src/components/DesignStudio/Surface.tsx frontend/src/__tests__/selectedToolbarText.test.tsx
git commit -m "feat(canvas): give the text element its own labelled, autofocused field

The content input was 112px, text-xs and unlabelled, wedged between the
font dropdown and the sliders. Now a full-width labelled row that focuses
and selects while the content is still the placeholder.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `profanity.py` — pure severity scanner

**Files:**
- Create: `backend/app/services/profanity.py`
- Test: `backend/tests/test_profanity.py` (create)

**Interfaces:**
- Consumes: nothing (stdlib `re` only)
- Produces:
  - `scan(text: str | None) -> str` returning exactly `"clean"`, `"mild"` or `"severe"`
  - `find_terms(text: str | None) -> list[str]` — matched terms, lowercased, de-duplicated, in first-appearance order
  - `MILD_TERMS: frozenset[str]`, `SEVERE_TERMS: frozenset[str]`
  - `_rebuild() -> None` — recompiles the patterns from the current term sets, so a test can inject terms without the repo containing slurs

**Naming:** `CLEAN`/`MILD`/`SEVERE` are the verdict **strings**; `MILD_TERMS`/
`SEVERE_TERMS` are the word **sets**. Do not conflate them.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_profanity.py`:

```python
"""The scanner is pure — no LLM, no I/O — so it can never stall a turn.

Severe-tier tests inject synthetic sentinels via `_rebuild()` rather than
hardcoding slurs, so the suite stays readable and the real list can change
without touching these tests.
"""
import pytest

from app.services import profanity


@pytest.fixture
def severe_sentinel(monkeypatch):
    """Swap the severe list for a harmless sentinel and recompile."""
    monkeypatch.setattr(profanity, "SEVERE_TERMS", frozenset({"zzslur"}))
    profanity._rebuild()
    yield "zzslur"
    monkeypatch.undo()
    profanity._rebuild()


@pytest.mark.parametrize("text", [
    "",
    None,
    "I need 50 caps for our club",
    # Substring traps. Matching inside words is the Scunthorpe problem and the
    # exact shape of the documented is_negative("another" contains "no") bug.
    "Scunthorpe United",
    "please send an assessment",
    "a classic six-panel",
    "Cockburn Rangers",
    "Essex County",
    "shitake mushrooms are not a swear word",
    "Bassetlaw",
])
def test_clean_text_is_clean(text):
    assert profanity.scan(text) == "clean"


@pytest.mark.parametrize("text", [
    "this is fucking slow",
    "that looks like shit",
    "F*CK this thing",
    "you absolute wanker",
])
def test_mild_profanity_is_mild(text):
    assert profanity.scan(text) == "mild"


def test_severe_terms_are_severe(severe_sentinel):
    assert profanity.scan(f"you {severe_sentinel}") == "severe"


def test_severe_outranks_mild_in_the_same_message(severe_sentinel):
    assert profanity.scan(f"this is shit you {severe_sentinel}") == "severe"


def test_find_terms_returns_matches_deduplicated_in_order():
    assert profanity.find_terms("shit, piss, shit again") == ["shit", "piss"]


def test_find_terms_is_empty_for_clean_text():
    assert profanity.find_terms("a navy trucker cap") == []


def test_matching_is_case_insensitive():
    assert profanity.scan("SHIT") == "mild"


def test_the_two_tiers_do_not_overlap():
    assert not (profanity.MILD_TERMS & profanity.SEVERE_TERMS)


def test_the_severe_list_is_populated():
    """An empty severe list makes the chat decline in orchestrator_v2 dead code."""
    assert profanity.SEVERE_TERMS


def test_scan_never_raises_on_odd_input():
    for value in (None, "", "   ", "🎩", "a" * 10_000):
        assert profanity.scan(value) in {"clean", "mild", "severe"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_profanity.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.profanity'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/profanity.py`:

```python
"""Deterministic profanity scanner — two severity tiers, no model call.

Deliberately PURE: no LLM, no network, no DB. `moderation.check_text` is the
LLM judge and fails open on any error; this one cannot fail at all, which is
what lets the cap-text gate block a design without risking a stall.

Matching is WORD-BOUNDARY ONLY. Substring matching would flag "Scunthorpe",
"assessment" and "classic" — the same class of bug as `state_machine.is_negative`
matching "no" inside "another", which is a documented live landmine here. Leet
variants are listed EXPLICITLY rather than produced by a normalisation pass,
because normalising would reintroduce exactly the false positives the word
boundaries are there to prevent.

Both lists are deliberately conservative: a false positive on the cap path stops
a customer at the very end of the funnel.
"""
from __future__ import annotations

import re

CLEAN = "clean"
MILD = "mild"
SEVERE = "severe"

#: Common obscenity. Tolerated in conversation, blocked on the product.
#:
#: Deliberately EXCLUDES the mildest swears — "hell", "damn", "crap", "bugger".
#: They are printable: blocking a cap reading "HELL RAISERS" is a worse outcome
#: for the store than letting it through, and the cap path is a hard stop at the
#: very end of the funnel. Tune this set, not the matching logic.
MILD_TERMS: frozenset[str] = frozenset({
    "arse", "arsehole", "ass", "asshole", "bastard", "bitch", "bollocks",
    "dick", "dickhead", "dumbass", "fuck", "fucked", "fucker", "fucking",
    "piss", "pissed", "prick", "shit", "shite", "shitty", "slut", "twat",
    "wanker", "whore",
    # Explicit obfuscations — listed, never derived. A general leet-normalising
    # pass would reintroduce exactly the false positives the word boundaries
    # exist to prevent.
    "f*ck", "f**k", "fck", "fuk", "sh*t", "sh1t", "b*tch", "a**hole",
})

#: Slurs and hate terms — declined on sight in chat, and blocked on the product.
#:
#: MUST be populated. An empty set makes the chat decline in `orchestrator_v2`
#: dead code, and `test_the_severe_list_is_populated` fails. Populate with
#: racial, ethnic, religious, sexual-orientation and gender-identity epithets;
#: source them from an established blocklist (e.g. the hate-speech subset of the
#: widely-mirrored LDNOOBW list) rather than composing one by hand. They are
#: deliberately not enumerated in the plan document that specified this module.
#:
#: Same word-boundary rules apply — check for reclaimed//homographic terms that
#: appear inside ordinary words before adding them.
SEVERE_TERMS: frozenset[str] = frozenset({
    # <- populate per the note above
})


def _pattern(terms: frozenset[str]) -> re.Pattern | None:
    """One alternation, longest-first so "fucking" wins over "fuck".

    `(?<!\\w)` / `(?!\\w)` rather than `\\b`: several terms end in a non-word
    character (`f**k`), and `\\b` after `*` asserts the opposite of what is
    meant. Lookarounds around the whole alternation are correct for both.
    """
    if not terms:
        return None
    ordered = sorted(terms, key=len, reverse=True)
    return re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(t) for t in ordered) + r")(?!\w)",
        re.IGNORECASE,
    )


_MILD_RE = _pattern(MILD_TERMS)
_SEVERE_RE = _pattern(SEVERE_TERMS)


def _rebuild() -> None:
    """Recompile from the CURRENT term sets.

    A test seam: it lets `test_profanity` inject a harmless sentinel into
    `SEVERE_TERMS` and exercise the severe tier without the repository or the
    test suite containing actual slurs.
    """
    global _MILD_RE, _SEVERE_RE
    _MILD_RE = _pattern(MILD_TERMS)
    _SEVERE_RE = _pattern(SEVERE_TERMS)


def _matches(pattern: re.Pattern | None, text: str) -> list[str]:
    if pattern is None:
        return []
    return [m.group(0).lower() for m in pattern.finditer(text)]


def scan(text: str | None) -> str:
    """``"clean"`` | ``"mild"`` | ``"severe"`` — severe wins over mild."""
    if not text or not text.strip():
        return CLEAN
    if _matches(_SEVERE_RE, text):
        return SEVERE
    if _matches(_MILD_RE, text):
        return MILD
    return CLEAN


def find_terms(text: str | None) -> list[str]:
    """Matched terms, lowercased and de-duplicated, in first-appearance order.

    Safe to log: terms only, never the surrounding message (security rule 10).
    """
    if not text or not text.strip():
        return []
    seen: dict[str, None] = {}
    for term in _matches(_SEVERE_RE, text) + _matches(_MILD_RE, text):
        seen.setdefault(term, None)
    return list(seen)
```

- [ ] **Step 4: Populate `SEVERE_TERMS`**

Fill the set per the note in its docstring. `test_the_severe_list_is_populated`
fails while it is empty, and until it is populated the chat decline added in
Task 4 can never fire — the feature would ship dead.

Before adding any term, check it does not appear inside an ordinary word or a
place name; the word-boundary anchors protect against prefixes and suffixes, not
against a term that is legitimately a substring of nothing but is itself an
ordinary word in another context.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_profanity.py -q`
Expected: PASS, with **no skips** (the parametrised cases expand to ~23 test ids)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/profanity.py backend/tests/test_profanity.py
git commit -m "feat(moderation): add a pure two-tier profanity scanner

Word-boundary only — substring matching is the Scunthorpe problem and the
same shape as the documented is_negative('another') landmine. No LLM and
no I/O, so it can never stall a turn.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Chat-side lenient guard

**Files:**
- Modify: `backend/app/prompts.py` (new constant near `V2_AWAIT_VERIFY_RETRY`, ~line 1198)
- Modify: `backend/app/services/conversation/orchestrator_v2.py:85-98`
- Test: `backend/tests/test_orchestrator_v2.py`

**Interfaces:**
- Consumes: `profanity.scan(text) -> str` from Task 3; `v2.reply_for(step, collected, *, persona, intro, ack="", colour_note="") -> str`; `_persist(sb, session_id, collected, step, reply, state_before, new_state, *, user_message=..., data=..., config=...)`
- Produces: `prompts.V2_ABUSE_DECLINE: str`

**Context:** the blank-turn no-op at `orchestrator_v2.py:85-98` is the exact precedent — re-render the current step, ingest nothing. This guard sits immediately after it, so a blank turn is still handled first.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_orchestrator_v2.py`. Follow the fixture style already
used in that file for a session parked mid-flow — **remember that
`email_captured: True` alone now parks a session at `AWAIT_EMAIL_VERIFY`, so
"past the email step" means `email_captured` AND `email_verified`.**

```python
@pytest.mark.anyio
async def test_severe_abuse_re_renders_the_step_and_ingests_nothing(monkeypatch):
    """A slur must not advance the flow, and must not reach the interpreter."""
    from app.services import profanity
    from app.services.conversation import orchestrator_v2 as o2

    monkeypatch.setattr(profanity, "scan", lambda t: "severe")

    async def _boom(*a, **k):
        raise AssertionError("interpreter must not run on a declined turn")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    sess = _session(state="ask_quantity", collected={
        "name": "Sam", "logos_done": True, "decor_done": True,
    })
    res = await o2.handle_message(sess["id"], "you are a <slur>")

    assert res["state"] == "ask_quantity"
    assert prompts.V2_ABUSE_DECLINE in res["reply"]
    assert "quantity" not in _reload(sess["id"])["collected"]


@pytest.mark.anyio
async def test_mild_profanity_does_not_block_the_funnel(monkeypatch):
    """Venting must not dead-end a sale — a mild turn is processed normally."""
    from app.services import profanity
    from app.services.conversation import orchestrator_v2 as o2

    monkeypatch.setattr(profanity, "scan", lambda t: "mild")

    sess = _session(state="ask_quantity", collected={
        "name": "Sam", "logos_done": True, "decor_done": True,
    })
    res = await o2.handle_message(sess["id"], "50 of the bloody things")

    assert prompts.V2_ABUSE_DECLINE not in res["reply"]
    assert res["state"] != "ask_quantity"


@pytest.mark.anyio
async def test_the_decline_is_a_normal_reply_not_an_error(monkeypatch):
    """A 422 renders as an error banner and reads as a broken app."""
    from app.services import profanity
    from app.services.conversation import orchestrator_v2 as o2

    monkeypatch.setattr(profanity, "scan", lambda t: "severe")
    sess = _session(state="ask_quantity", collected={"name": "Sam"})
    res = await o2.handle_message(sess["id"], "abuse")
    assert isinstance(res.get("reply"), str) and res["reply"]
```

Adapt `_session` / `_reload` to whatever helpers that file already defines.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_orchestrator_v2.py -q -k "abuse or mild_profanity"`
Expected: FAIL — `AttributeError: module 'app.prompts' has no attribute 'V2_ABUSE_DECLINE'`

(Note: this file's tests run with the v2 flag ON — do not set `CANVAS_ORCHESTRATOR_V2=false` here.)

- [ ] **Step 3: Add the decline copy**

In `backend/app/prompts.py`, after `V2_AWAIT_VERIFY_RETRY` (~line 1198):

```python
# Shown when a customer turn contains a slur or hate term. The flow does NOT
# advance and nothing is ingested — this is a boundary, not a rejection of the
# customer. Formal register, matching the rest of v2 (test_v2_copy_guards).
V2_ABUSE_DECLINE = (
    "I am not able to continue with that language, but I am happy to keep "
    "helping with your design."
)
```

- [ ] **Step 4: Add the guard**

In `backend/app/services/conversation/orchestrator_v2.py`, add the import beside
the other service imports at the top of the file. **This module currently binds
no logger** — add one, matching the convention in `app/services/leads.py:19,25`:

```python
import structlog

from app.services import profanity

log = structlog.get_logger()
```

(`structlog` goes with the stdlib/third-party imports, `log = …` at module level
below the imports.)

Then insert immediately AFTER the blank-turn no-op block (after line 98, before
the `# A real forward answer re-enables Back:` comment):

```python
    # Severe abuse (slurs / hate terms) is declined WITHOUT advancing: re-render
    # the current step exactly as the blank-turn guard above does, ingesting
    # nothing, so no slot is written and first-unmet routing cannot move. Mild
    # profanity deliberately falls straight through — a frustrated customer
    # venting must not dead-end a sale.
    #
    # A normal reply, never a 422: an error banner reads as a broken app rather
    # than a boundary. `find_terms` logs the matched TERM only — never the
    # message, name or email (security rule 10).
    if profanity.scan(message) == "severe":
        log.info("v2_turn_declined_abuse", terms=profanity.find_terms(message))
        reply = f"{prompts.V2_ABUSE_DECLINE} " + v2.reply_for(
            step, collected, persona=persona, intro=intro, colour_note=colour_note)
        return await _persist(sb, session_id, collected, step, reply.strip(),
                              state_before, current, user_message=message,
                              data=_public(step, collected, flow_config))
```

`_public` is already defined in this module at line 34 with the signature
`_public(step, collected, config=None)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_orchestrator_v2.py -q`
Expected: PASS

- [ ] **Step 6: Run the copy guards**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_v2_copy_guards.py -q`
Expected: PASS. `V2_ABUSE_DECLINE` must not contain any `_CASUAL` phrase ("pop your", "grab your", "love where", "no worries", "are you after", "tap") or the string "under the cap".

- [ ] **Step 7: Commit**

```bash
git add backend/app/prompts.py backend/app/services/conversation/orchestrator_v2.py backend/tests/test_orchestrator_v2.py
git commit -m "feat(chat-v2): decline slurs without advancing, let mild profanity through

Mirrors the blank-turn no-op: re-render the step, ingest nothing. A normal
reply rather than a 422, so venting never shows an error banner.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Cap-side strict gate at finalize

**Files:**
- Modify: `backend/app/api/routes/sessions.py` (inside `finalize_canvas`, right after `canvas_to_elements`, ~line 226)
- Test: `backend/tests/test_canvas_routes.py`

**Interfaces:**
- Consumes: `profanity.scan(text) -> str` and `profanity.find_terms(text) -> list[str]` from Task 3
- Produces: nothing

**Context:** `finalize_canvas` mints the reference code, writes `collected`, and triggers the sales email. The scan must precede all of it — a rejected design must not notify sales. `Surface.tsx:271-279`'s error banner already surfaces the 422.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_canvas_routes.py`. The fixtures (`client`,
`seeded_store_headers`, `canvas_session_id`) and the
`client._fake.design_sessions.rows[…]` reload idiom are the ones that file
already uses — see `test_v2_finalize_is_quote_gated_and_never_generates`.

```python
def _design_with_text(content: str) -> dict:
    return {"colourway": None, "faces": {
        "front": [{"id": "e1", "type": "text", "content": content,
                   "x": 0.5, "y": 0.4, "width": 0.3, "height": 0.1,
                   "rotation": 0, "zIndex": 0}],
        "back": [], "left": [], "right": []}}


def test_finalize_rejects_obscene_cap_text(client, seeded_store_headers, canvas_session_id):
    """Cap text reaches the AI render and then physical production artwork."""
    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": _design_with_text("SHIT HAPPENS")},
                    headers=seeded_store_headers)
    assert r.status_code == 422
    assert "SHIT HAPPENS" in r.json()["detail"]   # names it so it can be edited


def test_finalize_rejection_writes_nothing(client, seeded_store_headers, canvas_session_id):
    """The gate runs before the collected write and before the sales notify."""
    client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                json={"canvas_design": _design_with_text("SHIT HAPPENS")},
                headers=seeded_store_headers)
    row = client._fake.design_sessions.rows[canvas_session_id]
    assert not (row.get("collected") or {}).get("canvas_finalized")
    assert row.get("canvas_design") is None


def test_finalize_accepts_clean_cap_text(client, seeded_store_headers, canvas_session_id):
    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": _design_with_text("MADHATS CREW")},
                    headers=seeded_store_headers)
    assert r.status_code == 200
```

If the seeded session already carries a `canvas_design`, assert it is *unchanged*
rather than `None` in the second test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_canvas_routes.py -q -k obscene`
Expected: FAIL — status 200, not 422

- [ ] **Step 3: Write the implementation**

In `backend/app/api/routes/sessions.py`, add to the imports:

```python
from app.services import profanity
```

Then in `finalize_canvas`, immediately after:

```python
    elements, description = canvas_describe.canvas_to_elements(body.canvas_design)
```

insert:

```python
    # STRICT on the product, unlike chat. Anything here is rendered by the image
    # model and then produced as physical artwork, so BOTH tiers are blocked —
    # not just slurs. Runs before every write and before the reference/sales
    # side-effects below, so a rejected design notifies nobody.
    for el in elements:
        if el.get("type") != "text":
            continue
        content = el.get("content") or ""
        if profanity.scan(content) != "clean":
            log.info("canvas_finalize_rejected_profanity",
                     terms=profanity.find_terms(content))   # terms only — no PII
            raise HTTPException(
                status_code=422,
                detail=(f'We can\'t put "{content}" on a product. '
                        "Please edit that text and try again."),
            )
    for note in (collected.get("brief_notes") or []):
        if profanity.scan(str(note)) != "clean":
            log.info("canvas_finalize_rejected_profanity_note",
                     terms=profanity.find_terms(str(note)))
            raise HTTPException(
                status_code=422,
                detail="Please reword your note to the team and try again.",
            )
```

`sessions.py` already binds `log = structlog.get_logger()` at line 29 — no logger
setup is needed here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_canvas_routes.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/sessions.py backend/tests/test_canvas_routes.py
git commit -m "feat(canvas): block obscene cap text at finalize, before any side-effect

Strict on the product where chat is lenient: this text is rendered and
then physically produced. Runs before the reference is minted and before
sales is notified, so a rejected design notifies nobody.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Adjust panel — responsive placement

**Files:**
- Create: `frontend/src/lib/useIsDesktop.ts`
- Modify: `frontend/src/components/DesignStudio/SelectedToolbar.tsx` (props + sizing, lines 25-30, 49-67, 104-111)
- Modify: `frontend/src/components/DesignStudio/Surface.tsx:310-338`
- Test: `frontend/src/__tests__/adjustPanelPlacement.test.tsx` (create)

**Interfaces:**
- Consumes: `SelectedToolbar` (Task 2's version)
- Produces:
  - `useIsDesktop(): boolean` from `frontend/src/lib/useIsDesktop.ts`
  - `SelectedToolbar` accepts `{ variant?: 'rail' | 'stacked' }`, defaulting to `'stacked'`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/__tests__/adjustPanelPlacement.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, renderHook, screen } from '@testing-library/react'
import { SelectedToolbar } from '../components/DesignStudio/SelectedToolbar'
import { useCanvasStore, TEXT_PLACEHOLDER } from '../store/canvasStore'
import { useIsDesktop } from '../lib/useIsDesktop'

function setMatchMedia(matches: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true, configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches, media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    })),
  })
}

describe('useIsDesktop', () => {
  afterEach(() => {
    // @ts-expect-error — restore jsdom's default (absent)
    delete window.matchMedia
  })

  it('falls back to desktop when matchMedia is absent (jsdom)', () => {
    // @ts-expect-error — jsdom ships no matchMedia
    delete window.matchMedia
    const { result } = renderHook(() => useIsDesktop())
    expect(result.current).toBe(true)
  })

  it('reports mobile when the md query does not match', () => {
    setMatchMedia(false)
    const { result } = renderHook(() => useIsDesktop())
    expect(result.current).toBe(false)
  })

  it('reports desktop when the md query matches', () => {
    setMatchMedia(true)
    const { result } = renderHook(() => useIsDesktop())
    expect(result.current).toBe(true)
  })
})

describe('SelectedToolbar variants', () => {
  beforeEach(() => {
    useCanvasStore.setState({
      faces: { front: [], back: [], left: [], right: [] },
      activeFace: 'front', selectedId: null,
    })
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
  })

  it('is sticky in the stacked (mobile) variant, where it shares a column with the cap', () => {
    render(<SelectedToolbar variant="stacked" />)
    expect(screen.getByTestId('adjust-panel').className).toContain('sticky')
  })

  it('is NOT sticky in the rail variant — the rail column scrolls itself', () => {
    render(<SelectedToolbar variant="rail" />)
    expect(screen.getByTestId('adjust-panel').className).not.toContain('sticky')
  })

  it('applies no height cap in the rail variant, where it competes with nothing', () => {
    render(<SelectedToolbar variant="rail" />)
    const controls = screen.getByTestId('adjust-controls')
    expect(controls.style.maxHeight).toBe('')
  })

  it('defaults to stacked when no variant is given', () => {
    render(<SelectedToolbar />)
    expect(screen.getByTestId('adjust-panel').className).toContain('sticky')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/__tests__/adjustPanelPlacement.test.tsx`
Expected: FAIL — cannot resolve `../lib/useIsDesktop`

- [ ] **Step 3: Create the hook**

Create `frontend/src/lib/useIsDesktop.ts`:

```ts
import { useEffect, useState } from 'react'

/** Tailwind's `md` breakpoint. Kept in sync with the `md:` classes in Surface. */
const DESKTOP_QUERY = '(min-width: 768px)'

/**
 * True at `md` and above.
 *
 * Feature-detected, and it falls back to `true` rather than `false`: jsdom
 * ships no `matchMedia` (nor `ResizeObserver` — the same trap the observers in
 * SelectedToolbar guard against), and constructing one unconditionally throws
 * through every test that mounts Surface. Desktop is the right fallback because
 * it is the layout the existing suite expects.
 *
 * Used to mount the Adjust panel in ONE column or the other. Rendering it in
 * both behind `md:hidden` / `hidden md:block` would put two
 * `data-testid="adjust-panel"` nodes in the DOM and break every getByTestId.
 */
export function useIsDesktop(): boolean {
  const supported = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  const [isDesktop, setIsDesktop] = useState(() =>
    supported ? window.matchMedia(DESKTOP_QUERY).matches : true)

  useEffect(() => {
    if (!supported) return
    const mq = window.matchMedia(DESKTOP_QUERY)
    const onChange = (e: MediaQueryListEvent) => setIsDesktop(e.matches)
    setIsDesktop(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [supported])

  return isDesktop
}
```

- [ ] **Step 4: Add the variant prop to SelectedToolbar**

In `frontend/src/components/DesignStudio/SelectedToolbar.tsx`:

Change the signature (line 25):

```tsx
/** `stacked` shares the centre column with the cap (mobile) — capped and
 *  sticky. `rail` sits in the tool rail below the Done button (desktop), where
 *  it competes with nothing, so it takes no height cap and needs no sticky. */
export function SelectedToolbar({ variant = 'stacked' }: { variant?: 'rail' | 'stacked' } = {}) {
```

Replace the measuring effect body (lines 52-67) with:

```tsx
  useEffect(() => {
    const col = rootRef.current?.parentElement
    if (!col) return
    const measure = () => {
      // Only the stacked variant caps its height: there it steals pixels from
      // the cap, which CanvasStage sizes from the leftover column height. In the
      // rail there is no cap beside it — the column's own overflow-y-auto
      // handles a long panel.
      //
      // The rail wrapper is content-SIZED in height, so measuring it would be a
      // feedback loop (panel height -> wrapper height -> panel height). Its
      // WIDTH is class-driven and independent, so `compact` is safe to measure
      // in both variants.
      setMaxH(variant === 'rail'
        ? null
        : Math.max(MIN_MAX_H, Math.round(col.clientHeight * MAX_SHARE)))
      setCompact(col.clientWidth < COMPACT_BELOW)
    }
    measure()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    ro?.observe(col)
    window.addEventListener('resize', measure)
    return () => { ro?.disconnect(); window.removeEventListener('resize', measure) }
  }, [el?.id, variant])
```

Replace the root and controls elements (lines 104-111) with:

```tsx
  return (
    <div ref={rootRef} data-testid="adjust-panel"
      className={`${variant === 'stacked' ? 'sticky top-0 z-20 ' : ''}w-full shrink-0 bg-surface border border-accent rounded-xl overflow-hidden shadow-sm`}>
      <div className="bg-accent text-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide">
        Adjust — {ADJUST_LABELS[el.type] ?? 'Element'}
      </div>
      <div data-testid="adjust-controls"
        className="flex flex-wrap items-center gap-1.5 p-2 overflow-y-auto"
        style={maxH ? { maxHeight: maxH } : undefined}>
```

- [ ] **Step 5: Move the panel in Surface**

In `frontend/src/components/DesignStudio/Surface.tsx`:

Add the import: `import { useIsDesktop } from '../../lib/useIsDesktop'`

Add beside the other hooks in the component body:

```tsx
  const isDesktop = useIsDesktop()
  const showAdjust = isV2 ? v2Editing : unlocked
```

Replace the centre-column panel line (line 311):

```tsx
          {showAdjust && !isDesktop && <SelectedToolbar variant="stacked" />}
```

And add the rail-column mount — inside the right-rail wrapper, AFTER `<ToolRail … />`
(after line 337, before the closing `</div>` on line 338):

```tsx
          {/* Desktop home for the Adjust panel: the free space below "Design
              saved". The rail root is content-sized (no h-full — adding one
              would push this off-screen via mt-auto on the Done button), so
              this simply follows it. The wrapper mirrors ToolRail's own width
              and padding so the column width is class-driven, not content-driven. */}
          {showAdjust && isDesktop && (
            <div className="w-full md:w-44 lg:w-52 xl:w-64 px-3 xl:px-4 pb-3">
              <SelectedToolbar variant="rail" />
            </div>
          )}
```

- [ ] **Step 6: Run the placement tests**

Run: `cd frontend && npx vitest run src/__tests__/adjustPanelPlacement.test.tsx`
Expected: PASS (7 tests)

- [ ] **Step 7: Verify exactly one panel mounts, and no regressions**

Run: `cd frontend && npx vitest run src/__tests__/surfaceDirective.test.tsx src/__tests__/selectedToolbarText.test.tsx src/__tests__/ToolRail.test.tsx src/__tests__/canvasStoreLock.test.ts src/__tests__/lockedNode.test.tsx`
Expected: PASS. Any existing assertion that the panel is the first child of the centre column must be updated — under jsdom `useIsDesktop()` returns `true`, so the panel now mounts in the rail.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/useIsDesktop.ts frontend/src/components/DesignStudio/SelectedToolbar.tsx frontend/src/components/DesignStudio/Surface.tsx frontend/src/__tests__/adjustPanelPlacement.test.tsx
git commit -m "feat(canvas): move the Adjust panel into the rail's free space on desktop

Below md it stays above the cap — the rail stacks under the canvas on a
phone, which is the under-the-fold problem the 2026-07-26 change fixed.
One instance, placed by a feature-detected matchMedia hook, so there is
never a second adjust-panel node in the DOM.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Fix per-element assets and label the background flag

**Files:**
- Modify: `backend/app/services/components.py:44-47`
- Test: `backend/tests/test_components.py` (create if absent)

**Interfaces:**
- Consumes: `collected["elements"]` as written by `canvas_describe._element` — each element carries `type`, `content`, `assetPath`, `remove_bg`, `placement_zone`, and `canvas: {face, …}`
- Produces: `enumerate_components(collected, generation=None) -> list[dict]` — unchanged signature, richer labels

**Context:** `components.py:45` reads `el.get("asset_path")`, but `canvas_describe.py:103` writes `assetPath`. Per-element canvas assets therefore appear in **no** admin component list and **no** sales attachment today. This is a pre-existing bug, fixed here because a "remove background" note beside an undownloadable image is useless.

- [ ] **Step 1: Write the failing tests**

Create/extend `backend/tests/test_components.py`:

```python
from app.services.components import enumerate_components


def _canvas_element(**over):
    """Shaped exactly as canvas_describe._element writes it (camelCase asset)."""
    el = {"type": "logo", "content": "uploaded logo/artwork",
          "assetPath": "uploads/logo.png", "remove_bg": False,
          "placement_zone": "front", "canvas": {"face": "front"}}
    el.update(over)
    return el


def test_camelcase_assetpath_is_found():
    """canvas_describe writes assetPath; reading only asset_path meant canvas
    elements appeared in no admin list and no sales attachment."""
    out = enumerate_components({"elements": [_canvas_element()]})
    assert any(c["path"] == "uploads/logo.png" for c in out)


def test_v1_snake_case_asset_path_still_works():
    out = enumerate_components({"elements": [
        {"type": "logo", "asset_path": "uploads/old.png"}]})
    assert any(c["path"] == "uploads/old.png" for c in out)


def test_flagged_element_label_says_the_background_must_be_removed():
    out = enumerate_components({"elements": [_canvas_element(remove_bg=True)]})
    label = next(c["label"] for c in out if c["path"] == "uploads/logo.png")
    assert "BACKGROUND TO BE REMOVED" in label


def test_unflagged_element_label_does_not():
    out = enumerate_components({"elements": [_canvas_element(remove_bg=False)]})
    label = next(c["label"] for c in out if c["path"] == "uploads/logo.png")
    assert "BACKGROUND" not in label.upper()


def test_label_names_the_face():
    out = enumerate_components({"elements": [_canvas_element()]})
    label = next(c["label"] for c in out if c["path"] == "uploads/logo.png")
    assert "front" in label.lower()


def test_external_urls_are_still_excluded():
    out = enumerate_components({"elements": [
        _canvas_element(assetPath="https://cdn.example.com/x.png")]})
    assert not any("example.com" in c["path"] for c in out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_components.py -q`
Expected: FAIL — `test_camelcase_assetpath_is_found`

- [ ] **Step 3: Write the implementation**

In `backend/app/services/components.py`, add above `enumerate_components`:

```python
def _element_asset_path(el: dict):
    """`canvas_describe._element` writes camelCase `assetPath`; v1-shaped
    elements use `asset_path`. Reading only the snake form is why per-element
    canvas assets appeared in no admin component list and no sales attachment."""
    return el.get("assetPath") or el.get("asset_path")


def _element_label(index: int, el: dict) -> str:
    """Name the element and its face, and shout the background flag.

    Reads `remove_bg` — the field `prompt_builder` reads to instruct the render
    — never `collected["logos"][].bg`, which records the chip answer and is
    documented as able to diverge from the toggle.
    """
    kind = el.get("type") or "element"
    face = (el.get("canvas") or {}).get("face") or el.get("placement_zone")
    label = f"Element {index} — {kind}" + (f" ({face})" if face else "")
    if el.get("remove_bg"):
        label += " — BACKGROUND TO BE REMOVED"
    return label
```

Then replace the element loop (lines 44-47):

```python
    for i, el in enumerate(collected.get("elements") or [], start=1):
        p = _element_asset_path(el)
        if _is_storage_path(p):
            out.append({"label": _element_label(i, el), "path": p})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_components.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Check no existing caller asserted the old label**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/ -q -k "component or quote"`
Expected: PASS. Update any test asserting the literal `"Element 1 asset"`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/components.py backend/tests/test_components.py
git commit -m "fix(components): read camelCase assetPath and flag background removal

canvas_describe writes assetPath but components.py read asset_path, so
per-element canvas images were attached to nothing. Labels now name the
element, its face, and whether the background must be knocked out.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Design breakdown in the sales quote email

**Files:**
- Modify: `backend/app/services/design_summary.py` (add `design_breakdown`)
- Modify: `backend/app/prompts.py:827-844` (`SALES_QUOTE_REQUEST_EMAIL_BODY`)
- Modify: `backend/app/services/email.py:334-343`
- Test: `backend/tests/test_design_summary.py` and `backend/tests/test_email.py` (extend whichever exist)

**Interfaces:**
- Consumes: `collected["elements"]` (same shape as Task 7)
- Produces: `design_summary.design_breakdown(collected: dict) -> str` — one line per element, or `"—"` when there are none

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_design_summary.py`:

```python
from app.services.design_summary import design_breakdown


def test_breakdown_marks_the_element_needing_background_removal():
    out = design_breakdown({"elements": [
        {"type": "logo", "content": "uploaded logo/artwork",
         "remove_bg": True, "canvas": {"face": "front"}},
    ]})
    assert "BACKGROUND TO BE REMOVED" in out
    assert "front" in out.lower()


def test_breakdown_leaves_unflagged_elements_unmarked():
    out = design_breakdown({"elements": [
        {"type": "logo", "content": "uploaded logo/artwork",
         "remove_bg": False, "canvas": {"face": "front"}},
    ]})
    assert "BACKGROUND" not in out.upper()


def test_breakdown_lists_every_element():
    out = design_breakdown({"elements": [
        {"type": "text", "content": "MADHATS", "canvas": {"face": "front"}},
        {"type": "logo", "content": "uploaded logo/artwork",
         "remove_bg": True, "canvas": {"face": "back"}},
    ]})
    assert "MADHATS" in out
    assert len([ln for ln in out.splitlines() if ln.strip()]) == 2


def test_breakdown_with_no_elements_is_a_dash():
    assert design_breakdown({}) == "—"
```

Add to `backend/tests/test_email.py` (or the file that covers
`send_quote_request_to_sales`):

```python
def test_sales_email_body_carries_the_background_removal_flag(monkeypatch):
    sent = {}
    monkeypatch.setattr("app.services.email._dispatch",
                        lambda to, subj, html, attachments=None: sent.update(html=html) or True)
    from app.services import email as email_mod

    email_mod.send_quote_request_to_sales(
        recipient="sales@example.com", store_name="MadHats",
        customer_email="c@example.com", reference_code="MH-ABCDEF",
        collected={"elements": [
            {"type": "logo", "content": "uploaded logo/artwork",
             "remove_bg": True, "canvas": {"face": "front"}}]},
    )
    assert "BACKGROUND TO BE REMOVED" in sent["html"]
```

Match the real signature of `send_quote_request_to_sales` in `email.py` — adapt
the keyword names if they differ.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_design_summary.py tests/test_email.py -q -k "breakdown or background"`
Expected: FAIL — `ImportError: cannot import name 'design_breakdown'`

- [ ] **Step 3: Add the helper**

In `backend/app/services/design_summary.py`, append:

```python
def design_breakdown(collected: dict) -> str:
    """One line per design element for the INTERNAL sales notification.

    Separate from `customer_brief`, which is customer-facing and deliberately
    drops production detail. This one exists to carry that detail — above all
    the background-removal flag, which previously reached no admin surface at
    all and left sales quoting a job without knowing the artwork needed
    knocking out.

    Reads `remove_bg` (what the render acts on), never
    `collected["logos"][].bg` (the chip answer, documented as divergent).
    """
    lines: list[str] = []
    for i, el in enumerate(collected.get("elements") or [], start=1):
        etype = el.get("type") or "element"
        content = el.get("content") or ""
        face = (el.get("canvas") or {}).get("face") or el.get("placement_zone") or ""
        bits = [f"{i}. {etype}"]
        if content:
            bits.append(f'"{content}"' if etype == "text" else content)
        if face:
            bits.append(f"on the {face}")
        line = " — ".join([bits[0], ", ".join(bits[1:])]) if len(bits) > 1 else bits[0]
        if el.get("remove_bg"):
            line += "  ** BACKGROUND TO BE REMOVED **"
        lines.append(line)
    return "\n".join(lines) if lines else "—"
```

- [ ] **Step 4: Add the slot to the email body**

In `backend/app/prompts.py`, update the docstring comment above
`SALES_QUOTE_REQUEST_EMAIL_SUBJECT` to add `design_breakdown=` to the documented
`.format(...)` keys, and insert the block into `SALES_QUOTE_REQUEST_EMAIL_BODY`
between `Decoration method(s)` and `Notes`:

```
Decoration method(s): {decoration}

Design elements:
{design_breakdown}

Notes:
{notes}
```

- [ ] **Step 5: Fill the slot**

In `backend/app/services/email.py`, add the import
`from app.services.design_summary import design_breakdown` and add to the
`.format(...)` call at line 334:

```python
        design_breakdown=design_breakdown(collected),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_design_summary.py tests/test_email.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/design_summary.py backend/app/prompts.py backend/app/services/email.py backend/tests/test_design_summary.py backend/tests/test_email.py
git commit -m "feat(sales): list design elements and background removal in the quote email

Sales previously quoted and produced a job with no way to know the
artwork needed its background knocked out.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Surface the flag in the admin quote-requests view

**Files:**
- Modify: `backend/app/api/routes/admin_leads.py:69-91`
- Modify: `frontend/src/admin/adminApi.ts:62-83`
- Modify: `frontend/src/admin/views/QuoteRequestsView.tsx:29-41`
- Test: `backend/tests/test_admin_leads.py`; `frontend/src/__tests__/adminQuotes.test.tsx`

**Interfaces:**
- Consumes: `collected["elements"]` (same shape as Task 7)
- Produces:
  - Each `/admin/quote-requests` row gains `elements: [{kind, label, face, remove_bg}]`
  - TS `QuoteElement { kind: string; label: string; face: string | null; remove_bg: boolean }`, and `QuoteRequest.elements?: QuoteElement[]`

**Note:** `frontend/src/__tests__/adminQuotes.test.tsx` has 2 PRE-EXISTING failures (missing Router context). Confirm they still fail identically rather than treating them as caused by this task.

- [ ] **Step 1: Write the failing backend test**

Add to `backend/tests/test_admin_leads.py`:

```python
def test_quote_rows_expose_per_element_background_removal(client, quote_lead):
    res = client.get("/admin/quote-requests", headers=ADMIN_HEADERS)
    row = next(r for r in res.json() if r["lead_id"] == quote_lead["id"])
    flagged = [e for e in row["elements"] if e["remove_bg"]]
    assert flagged and flagged[0]["face"] == "front"


def test_quote_row_elements_carry_no_customer_pii(client, quote_lead):
    res = client.get("/admin/quote-requests", headers=ADMIN_HEADERS)
    row = next(r for r in res.json() if r["lead_id"] == quote_lead["id"])
    for el in row["elements"]:
        assert set(el) == {"kind", "label", "face", "remove_bg"}
```

Extend the file's existing `quote_lead` fixture so its session `collected`
includes:

```python
"elements": [
    {"type": "logo", "content": "uploaded logo/artwork",
     "remove_bg": True, "canvas": {"face": "front"}},
]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_leads.py -q -k background_removal`
Expected: FAIL — `KeyError: 'elements'`

- [ ] **Step 3: Add the summary to the payload**

In `backend/app/api/routes/admin_leads.py`, add above the list route:

```python
def _element_summary(collected: dict) -> list[dict]:
    """PII-free per-element detail for the quote row.

    Content only — never customer identity — matching this payload's existing
    boundary. `remove_bg` is read from the element (what the render acts on),
    never from `collected["logos"][].bg`, which is the chip answer.
    """
    out = []
    for el in collected.get("elements") or []:
        out.append({
            "kind": el.get("type") or "element",
            "label": el.get("content") or "",
            "face": (el.get("canvas") or {}).get("face") or el.get("placement_zone"),
            "remove_bg": bool(el.get("remove_bg")),
        })
    return out
```

Then add to the appended row dict, after the `"notes"` entry:

```python
                "elements": _element_summary(collected),
```

- [ ] **Step 4: Run backend test to verify it passes**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_leads.py -q`
Expected: PASS

- [ ] **Step 5: Add the frontend type**

In `frontend/src/admin/adminApi.ts`, add above `QuoteRequest`:

```ts
/** Per-element detail for a quote row. PII-free by construction on the server. */
export interface QuoteElement {
  kind: string
  label: string
  face: string | null
  remove_bg: boolean
}
```

and add to the `QuoteRequest` interface, after `notes`:

```ts
  elements?: QuoteElement[]
```

- [ ] **Step 6: Write the failing frontend test**

Add to `frontend/src/__tests__/adminQuotes.test.tsx`. Note the two existing tests
in this file `render(<QuoteRequestsView />)` bare and **fail** because the view
calls `useNavigate` with no Router in scope — that is the documented pre-existing
failure. Wrap the new test in `MemoryRouter` so it passes; do not "fix" the
existing two as part of this task.

Add the import at the top of the file:

```tsx
import { MemoryRouter } from 'react-router-dom'
```

Then append inside the `describe('QuoteRequestsView', …)` block:

```tsx
  const baseRow = {
    lead_id: 'l1', session_id: 's1', name: 'Jane', email: 'jane@x.com', phone: '123',
    notify_by_phone: true, quote_note: 'rush', quote_confirmed_at: '2026-07-01T00:00:00Z',
    product: 'Classic Cap', decoration_type: 'embroidery', placement_zone: 'front',
    quantity: 50, share_token: 'tok',
  }

  it('badges a row whose artwork needs its background removed', async () => {
    vi.mocked(listQuoteRequests).mockResolvedValue([
      {
        ...baseRow,
        elements: [
          { kind: 'text', label: 'MADHATS', face: 'front', remove_bg: false },
          { kind: 'logo', label: 'uploaded logo/artwork', face: 'front', remove_bg: true },
        ],
      },
    ])
    render(<MemoryRouter><QuoteRequestsView /></MemoryRouter>)
    expect(await screen.findByText('Remove BG')).toBeInTheDocument()
  })

  it('shows a dash when no element needs background removal', async () => {
    vi.mocked(listQuoteRequests).mockResolvedValue([
      { ...baseRow, elements: [{ kind: 'text', label: 'MADHATS', face: 'front', remove_bg: false }] },
    ])
    render(<MemoryRouter><QuoteRequestsView /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('jane@x.com')).toBeInTheDocument())
    expect(screen.queryByText('Remove BG')).not.toBeInTheDocument()
  })

  it('counts multiple flagged elements', async () => {
    vi.mocked(listQuoteRequests).mockResolvedValue([
      {
        ...baseRow,
        elements: [
          { kind: 'logo', label: 'a', face: 'front', remove_bg: true },
          { kind: 'logo', label: 'b', face: 'back', remove_bg: true },
        ],
      },
    ])
    render(<MemoryRouter><QuoteRequestsView /></MemoryRouter>)
    expect(await screen.findByText('Remove BG ×2')).toBeInTheDocument()
  })
```

- [ ] **Step 7: Add the badge column**

In `frontend/src/admin/views/QuoteRequestsView.tsx`, insert into `columns` after
the `decoration` entry:

```tsx
    {
      key: 'artwork',
      header: 'Artwork',
      render: (r) => {
        const n = (r.elements ?? []).filter((e) => e.remove_bg).length
        return n ? (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800"
            title="The customer asked for the background to be knocked out of this artwork">
            Remove BG{n > 1 ? ` ×${n}` : ''}
          </span>
        ) : '—'
      },
    },
```

- [ ] **Step 8: Run the frontend tests**

Run: `cd frontend && npx vitest run src/__tests__/adminQuotes.test.tsx`
Expected: the new test PASSES; the 2 pre-existing Router-context failures remain, unchanged.

- [ ] **Step 9: Commit**

```bash
git add backend/app/api/routes/admin_leads.py backend/tests/test_admin_leads.py frontend/src/admin/adminApi.ts frontend/src/admin/views/QuoteRequestsView.tsx frontend/src/__tests__/adminQuotes.test.tsx
git commit -m "feat(admin): badge quote rows whose artwork needs background removal

Per-element detail on /admin/quote-requests, PII-free, read from the same
field the render acts on.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Fix the session-detail background-removal row

**Files:**
- Modify: `frontend/src/admin/views/SessionDetailView.tsx:13-23` and the brief-card render (~line 123)
- Test: `frontend/src/__tests__/sessionDetailRemoveBg.test.tsx` (create)

**Interfaces:**
- Consumes: `SessionDetail.collected` — `elements[].remove_bg` (canvas) and top-level `remove_bg` (v1)
- Produces: nothing

**Context:** `BRIEF_FIELDS` includes `{ key: 'remove_bg', label: 'Remove background' }`, but that reads the **v1** top-level `collected.remove_bg`, set only by `state_machine.py:367` / `intent_extractor.py:515`. For a canvas session it is `undefined` and the row is filtered out entirely — so the view looks like it reports the flag while never doing so.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/sessionDetailRemoveBg.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { removeBgValue } from '../admin/views/SessionDetailView'

describe('remove-background brief row', () => {
  it('reports Yes when any canvas element is flagged', () => {
    expect(removeBgValue({ elements: [
      { type: 'logo', remove_bg: false },
      { type: 'logo', remove_bg: true },
    ] })).toBe(true)
  })

  it('reports No when canvas elements exist but none are flagged', () => {
    expect(removeBgValue({ elements: [{ type: 'logo', remove_bg: false }] })).toBe(false)
  })

  it('falls back to the v1 top-level flag when there are no elements', () => {
    expect(removeBgValue({ remove_bg: true })).toBe(true)
  })

  it('is undefined when neither source says anything', () => {
    expect(removeBgValue({})).toBeUndefined()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/sessionDetailRemoveBg.test.tsx`
Expected: FAIL — `removeBgValue` is not exported

- [ ] **Step 3: Add the resolver**

In `frontend/src/admin/views/SessionDetailView.tsx`, add below `BRIEF_FIELDS`:

```tsx
/**
 * Resolve the background-removal flag for the brief card.
 *
 * Canvas sessions record it PER ELEMENT (`elements[].remove_bg`) — the field
 * the render acts on. The top-level `collected.remove_bg` is the v1 chat flag
 * and is never set for a canvas session, so reading only that made this row
 * show "—" for every canvas design. Exported for test.
 */
export function removeBgValue(collected: Record<string, unknown>): boolean | undefined {
  const elements = collected?.elements
  if (Array.isArray(elements) && elements.length > 0) {
    return elements.some((el) => Boolean((el as { remove_bg?: boolean })?.remove_bg))
  }
  const legacy = collected?.remove_bg
  return typeof legacy === 'boolean' ? legacy : undefined
}
```

- [ ] **Step 4: Use it in the brief card**

In the brief-card render (~line 123), where `BRIEF_FIELDS` is mapped to values,
special-case the `remove_bg` key so it reads through the resolver rather than a
plain `collected[key]` lookup — for example:

```tsx
{BRIEF_FIELDS.map(({ key, label }) => {
  const value = key === 'remove_bg' ? removeBgValue(detail.collected) : detail.collected[key]
  if (value === undefined) return null
  return /* …existing row markup, rendering fmt(value)… */
})}
```

Keep the existing filter-out-when-undefined behaviour and the existing row
markup; only the value lookup changes.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/__tests__/sessionDetailRemoveBg.test.tsx`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the admin suite**

Run: `cd frontend && npx vitest run src/admin`
Expected: PASS (baseline 40 passing)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/admin/views/SessionDetailView.tsx frontend/src/__tests__/sessionDetailRemoveBg.test.tsx
git commit -m "fix(admin): read remove-background from canvas elements, not the v1 flag

The row read collected.remove_bg, which no canvas session sets, so it
showed '—' for every canvas design while looking like it reported the flag.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Full-suite verification and memory update

**Files:**
- Modify: `CLAUDE.md` (current implementation state)

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. Baseline before this work was **1057** passing — re-measure by stashing rather than trusting that number.

- [ ] **Step 2: Run the v2 suite with the flag ON**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_v2_copy_guards.py tests/test_state_machine_v2.py tests/test_canvas_steps.py -q`
Expected: PASS

- [ ] **Step 3: Run the frontend suites**

Run: `cd frontend && npx vitest run src/__tests__` then `npx vitest run src/admin`
Expected: baseline was **249 passing, 2 failing** (the 2 are pre-existing `adminQuotes` Router-context failures). New tests add to the passing count; the 2 failures must be unchanged.

- [ ] **Step 4: Update CLAUDE.md**

Add a bullet to §13 "Current implementation state" recording, concisely:
- the graded profanity model (pure scanner, lenient chat / strict cap) and that `SEVERE_TERMS` ships empty as a policy extension point
- the Adjust panel's responsive placement and the `useIsDesktop` fallback-to-desktop rule
- that `remove_bg` now reaches sales email, admin quote rows, component labels and session detail — all reading `elements[].remove_bg`, never `logos[].bg`
- the `assetPath`/`asset_path` fix and that per-element assets previously attached to nothing
- refreshed test counts

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(memory): record the studio fixes batch

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **Test helper names are indicative.** Each backend test file has its own
  fixtures (`client`, session builders, `ADMIN_HEADERS`, store-key constants).
  Use whatever that file already defines instead of introducing new ones.
- **`email_captured: True` alone parks a v2 session at `AWAIT_EMAIL_VERIFY`.**
  Any fixture meant to sit past the email step needs `email_verified: True` too.
- **Do not re-add canvas-level background processing.** The `removeBg` flag is a
  MARK: the AI render performs the knockout. Customer-facing copy must never
  promise processing or a wait.
- **Sub-768px cannot be observed in this environment.** Task 6's mobile branch
  rests on the matchMedia fallback and the class-pinning tests.
