# Conversational Per-Element Deep-Dive (InkyBay-parity) — Design Spec

Date: 2026-07-11
Branch: feat/smarter-studio
Status: Approved (brainstorm) — ready for implementation plan
Supersedes: the flat-brief gather loop + global placement from
`2026-07-11-wider-design-brief-design.md` (same branch, not yet merged)

## 1. Problem (found in live testing)

The just-shipped "gather loop" is too shallow and has a type bug:

1. **Type bug:** choosing "Add a graphic" enters the *same* generic
   `ADD_ELEMENTS_MODE` as "Add text" (both are in `_BARE_YES`); the loop records
   no element **type**, so a graphic request feels like it "keeps looping in the
   add-text loop."
2. **No depth:** when a customer adds something, the bot never asks the element's
   specifics — font, size, colour, where it goes. It should **dig deeper on that
   element before moving on**, "like a salesperson taking an order."
3. **Attributes can't bind to an element:** the flat brief
   (`design_description.text_elements[]`, `colours[]`, …) cannot associate "gold"
   with the team name vs. a star — attributes get mixed across elements.

The reference is MadHats' existing InkyBay design lab
(`madhats.com.au/pages/designlab/...`). Observed capabilities: **Edit Color**
(cap colourway), **Upload File**, **Add Text** (wording, printing colour, font
library, font size, alignment, letter/line spacing, outline & shadow, text shape
/curve, flip, duplicate/remove, free move/rotate/resize), **Add Graphic**
(clipart library), **Add Note** (note to team), **Preview**, **Get A Quote**, and
four decoration sides **Front / Back / Left / Right**. InkyBay treats every
addition as its own **object with its own attributes and its own placement**.

The Studio's job is different from InkyBay's canvas: gather that same intent
**conversationally**, then **generate a preview** (which InkyBay can't). InkyBay
stays live for pixel-level editing.

## 2. Goal & confirmed scope

Make each addition a first-class **element** the bot interrogates
salesperson-style before moving on, with attributes that bind to that element,
and per-element placement.

Confirmed decisions:
- **Depth:** full per-element deep-dive; ask attributes one at a time.
- **Attributes are deferrable:** "you choose" / "whatever looks good" / "the team
  decides" is always accepted and moves on. Only **content** is required.
- **Placement is per-element** (in the deep-dive). The single global placement
  question is removed; the pin tool stays for fine-tuning.
- **Element types this iteration:** text, graphic (described — no clipart-library
  UI), uploaded logo/artwork (as an element with its own size/placement/bg), and
  note-to-team.
- **Extra depth:** attributes only. Cap colourway stays tied to the product the
  customer picked (not re-asked in chat). Text effects (outline/shadow/curved)
  are a single optional "any special styling?" probe captured as free text.

**Out of scope (YAGNI — InkyBay keeps these):** clipart library UI, drag-drop
canvas, letter-spacing/line-height/flip micro-controls, size-quantity matrix,
in-chat cap-colour picker.

## 3. Design

### 3.1 Data model — a structured element list

`collected["elements"]`: an ordered list of decoration elements. Each:

```
{
  "type": "text" | "graphic" | "logo" | "note",
  "content": str,                 # text wording / graphic description /
                                  # note text / (logo: caption, optional)
  "font": str | null,             # text only
  "size": str | null,             # small | medium | large | free text
  "colour": str | null,
  "style": str | null,            # text effects (outline/shadow/curved) or art style
  "placement_zone": str | null,   # front_panel | side | back | under_brim (not for note)
  "placement_position": str | null,
  "remove_bg": bool | null,       # logo only
  "asset_path": str | null,       # logo only (uploaded artwork)
  "deferred": [str]               # attribute names the customer left to the team
}
```

`collected["pending_element"]`: the element currently being built in the
deep-dive. On completion it is appended to `elements` and cleared.

The flat `design_description` merge model from the prior spec is **retired** for
the gather path. A tiny compatibility shim keeps `design_description` populated
from `elements` only if any legacy consumer still reads it (see §3.6).

### 3.2 Attribute plans (per type)

`element_planner.next_attribute(element) -> str | None` returns the first
in-scope attribute that is neither set nor deferred, in this order; `None` = the
element is complete. `content` is required (cannot be deferred).

- **text:** `content`, `font`, `size`, `colour`, `style`, `placement_zone`,
  `placement_position`
- **graphic:** `content`, `style`, `size`, `colour`, `placement_zone`,
  `placement_position`
- **logo:** `remove_bg`, `size`, `placement_zone`, `placement_position`
  (`content`/asset already captured at upload)
- **note:** `content` only (no placement, no styling)

A per-element **done signal** ("that's good for this one", "just make it look
good", "you decide the rest") defers every remaining attribute at once →
element complete.

### 3.3 Conversation states

Replace `ADD_ELEMENTS_MODE` with an attribute-driven deep-dive; keep
`ASK_MORE_ELEMENTS` as the type chooser.

- `ASK_MORE_ELEMENTS` (offer): *"Anything to add — some text, a graphic, or a
  note for our team? Or say 'that's everything'."* Options:
  `["Add text", "Add a graphic", "Add a note", "That's everything"]`. Selecting a
  type sets `pending_element = {type, deferred: []}` and routes to
  `ELEMENT_DEEPDIVE`. "That's everything" (and no pending element) → exits the
  loop.
- `ELEMENT_DEEPDIVE` (loop): each turn, the interpreter extracts any attributes
  the customer volunteered into `pending_element`; then `next_attribute` picks
  the next gap and the reply asks for exactly that one (salesperson style,
  acknowledging what was just captured). A defer answer marks that attribute
  `deferred`. When `next_attribute` returns `None`, append `pending_element` to
  `elements`, clear it, and route back to `ASK_MORE_ELEMENTS` with "Added
  <content>. Anything else?".

The logo path funnels into the deep-dive too: `UPLOAD_LOGO` creates a
`pending_element{type:"logo", asset_path}` and routes into `ELEMENT_DEEPDIVE`
(which now owns `remove_bg` + size + placement), replacing the standalone
`ASK_REMOVE_BG` step. The describe path (`DESCRIBE_DESIGN`) creates a
`pending_element` (type inferred: pure wording → text, else graphic) with
`content` = the description and any attributes the extractor caught, then routes
into `ELEMENT_DEEPDIVE` to fill the gaps.

`ASK_PLACEMENT_ZONE` / `ASK_PLACEMENT_POSITION` (global) are **removed** from the
forward flow (placement is per-element now). They remain only as legacy enum
members if any test references them; the pin tool (`ASK_PIN_ANNOTATION`) is
unchanged and still offered once after all elements are gathered.

### 3.4 Dynamic reply wording

`ELEMENT_DEEPDIVE` cannot use a single static state prompt — the question depends
on the target attribute. `generate_reply` gains an `ask_for` parameter (the
attribute slug + light context, e.g. the element's content). With a Haiku key,
the instruction is *"acknowledge <captured>, then ask the customer for the
<attribute> of the <type> '<content>', making clear they can say 'you choose'."*
Without a key, a per-attribute template dict (`ATTRIBUTE_QUESTIONS`) supplies the
canned question. No PII enters the LLM context (reuse `_safe_collected`).

### 3.5 Deterministic extraction (no-key path)

`interpret_turn` / a new `extract_element_attributes(type, message)` maps a
message to attribute fields. With a key, Haiku returns the structured attributes.
Without a key, deterministic heuristics fill what they can (zone keywords, size
words small/medium/large, colour words, "you choose" → defer) and drop the rest —
acceptable degradation, consistent with the codebase. Content is captured
verbatim.

### 3.6 Prompt builder — one block per element

`prompt_builder` consumes `collected["elements"]` and emits, per non-note
element, a block describing type + set attributes at that element's placement,
skipping deferred/empty fields. Example line group:

```
- Embroidered text "TEAM SPIRIT", bold serif font, large, in gold,
  on the front panel (centre).
- A small star graphic, minimalist style, navy, on the left side.
```

- **logo** element → the existing SECOND-image directive + its size/placement.
- **note** element → appended as *"Customer note to the team: <content>"*
  (context for the design team; not a render instruction).
- The `IMAGE_GEN_PROMPT` is reworked so placement is expressed **per element**
  (the current single `{placement_zone}/{placement_position}` slots are replaced
  by the per-element block). The cap-fidelity lock, no-collage, and
  reference-photo constraints are unchanged.
- `build_params` still derives a representative placement (first element's, or a
  default) for any param that needs a single value, but the prompt text is
  per-element.

### 3.7 Goal planner

Drop the global placement goal. After the design-source branch, the flow is:
first element deep-dive (from logo/describe) → `ASK_MORE_ELEMENTS` (offered once
via `elements_offered`) → `ELEMENT_DEEPDIVE` per added element → `ASK_PIN_ANNOTATION`
→ `GENERATING`. `ELEMENT_DEEPDIVE` is a gate state (routed by `advance_state`).

### 3.8 Progress indicator

The deep-dive is variable-length and optional; it is **not** counted as discrete
steps. `progress()` normalizes `ASK_MORE_ELEMENTS` and `ELEMENT_DEEPDIVE` to the
design step (as the prior spec did for the gather states), so "Step X of N"
holds steady while the customer builds elements.

## 4. Frontend

Minimal. The new states emit standard `options` chips (`ChatPanel` renders chips
+ text input together). Add a **"You choose"** defer chip to `ELEMENT_DEEPDIVE`
attribute turns, and size/placement chips per attribute. No new components. The
existing on-screen preview + pin tool are unchanged; `RELEASED_STATES` unaffected
(all changes are pre-generation).

## 5. Testing

- `element_planner.next_attribute`: per-type attribute order; deferral skips;
  content required; done-signal completes.
- State machine: `ASK_MORE_ELEMENTS` type routing; `ELEMENT_DEEPDIVE` loop +
  completion → back to offer; logo/describe funnel into deep-dive; global
  placement removed from forward flow.
- Orchestrator: type recorded per element (graphic ≠ text); attribute extraction
  merges into `pending_element`; defer marks `deferred`; completed element pushed
  to `elements`; works with and without an LLM key.
- Prompt builder: per-element enumeration with per-element placement; deferred/
  empty attributes skipped; logo SECOND-image + note-as-context handled;
  fidelity/no-collage locks intact.
- Progress steady during the deep-dive.

## 6. Files touched (anticipated)

- New: `backend/app/services/conversation/element_planner.py` (next_attribute +
  completion + per-type attribute lists).
- `state_machine.py` — `ELEMENT_DEEPDIVE` state; retire global placement from the
  forward path; transitions/backtracks; `advance_state` deep-dive routing.
- `goal_planner.py` — drop global placement goal; deep-dive as gate.
- `orchestrator.py` — element creation (logo/describe/typed), attribute extraction
  into `pending_element`, defer handling, completion → `elements`, dynamic
  `ask_for` reply wiring, `_public_data` chips per attribute.
- `intent_extractor.py` — `extract_element_attributes` + `generate_reply(ask_for=)`;
  `ATTRIBUTE_QUESTIONS` canned templates.
- `prompt_builder.py` — consume `elements`; per-element block + per-element
  placement; note/logo handling.
- `prompts.py` — `ELEMENT_DEEPDIVE`/`ASK_MORE_ELEMENTS` copy; per-attribute
  question templates; reworked `IMAGE_GEN_PROMPT` placement.
- Tests across the above.
- Frontend: verify chips (incl. "You choose") render; no new components expected.

## 7. Migration / risk

This reworks code from the wider-brief feature (flat `merge_brief`, global
placement, `ADD_ELEMENTS_MODE`). Because that branch is not merged, we build
forward on it. `merge_brief` may be kept only if a legacy consumer needs the flat
shape; otherwise it is removed with its tests. The `IMAGE_GEN_PROMPT` placement
rework is the highest-risk change — its fidelity/no-collage assertions must stay
green.
