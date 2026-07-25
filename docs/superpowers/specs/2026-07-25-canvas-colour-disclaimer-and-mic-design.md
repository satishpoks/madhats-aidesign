# Canvas colour disclaimer + final notes, and Mac voice-mic messaging — Design

Date: 2026-07-25
Status: Draft (awaiting review)

## Summary

Two independent, small changes, both targeting the **v2 canvas flow**
(`CANVAS_ORCHESTRATOR_V2`, which production runs):

- **A. Voice mic on Mac Chrome** — the mic is already wired correctly
  (`getUserMedia` triggers the permission prompt). The blocking is
  **environmental** (insecure `http://` origin, and/or missing macOS Chrome mic
  permission), which the current error copy hides behind a misleading
  "unblock in the address bar" hint. Fix the messaging to be honest and
  Mac-aware; document the real (out-of-code) unblock.
- **B. New "colour disclaimer + final notes" step** — after the design review
  and before the quote request, show a colour-accuracy disclaimer with two
  admin-configurable reference-guide links, invite verbatim final notes
  (e.g. CMYK/Pantone or embroidery thread numbers) into the team brief, then
  advance to the existing `REQUEST_QUOTE` step unchanged.

These do not touch v1 (customise/blank Q&A) or any other flow.

---

## A. Voice mic on Mac Chrome

### Diagnosis

Voice is wired in `frontend/src/components/CustomiseStudio/ChatColumn.tsx`
(`usePushToTalk` → `useSpeechRecognition`). The mic button's `onPointerDown`
calls `speech.start()`, which already calls
`navigator.mediaDevices.getUserMedia({ audio: true })` — the correct way to
raise a permission prompt. So the code already "asks."

The block is environmental, and the current copy misleads:

1. **Insecure origin (most likely).** Prod is `http://madhats.getaiconsult.com.au:5173`.
   Chrome only grants mic / `getUserMedia` / Web Speech API on **HTTPS or
   `localhost`**. On plain HTTP, `navigator.mediaDevices` is `undefined`; the
   current `start()` falls through the `else` branch, sets `micReadyRef = true`,
   calls `rec.start()`, which fires `onerror` `not-allowed`, and we show
   `MIC_BLOCKED_MESSAGE` = *"click the camera/mic icon in your browser's address
   bar."* On HTTP there is **no** such icon and no way to grant — the message is
   wrong for this case.
2. **macOS system permission.** Even on HTTPS, if Chrome lacks OS mic access
   (System Settings → Privacy & Security → Microphone → Google Chrome),
   `getUserMedia` throws `NotAllowedError`. A web page cannot grant this; it can
   only point the user to the setting.

This session cannot reproduce Mac behaviour (Claude Code runs on Windows here),
so the fix is reasoned from the code and the documented Chrome/macOS
constraints, not a live Mac repro.

### Decision

**Keep the mic button visible** (do not hide it on insecure/unsupported
contexts). When the mic cannot be used, replace the misleading message with an
honest, context-specific one.

### Changes — `frontend/src/hooks/useSpeechRecognition.ts`

Replace the single `MIC_BLOCKED_MESSAGE` with a small set of specific messages
and pick the right one:

- **Insecure context** — at the top of `start()`, if
  `typeof window !== 'undefined' && window.isSecureContext === false`, set the
  message and return **before** touching `getUserMedia`:
  > "Voice needs a secure (https) connection, so it's unavailable on this site
  > right now. You can type your message instead."
- **`getUserMedia` rejection** — branch on `err.name`:
  - `NotAllowedError` / `SecurityError` → Mac-aware guidance:
    > "Microphone access is blocked. Allow it via the mic icon in the address
    > bar, and on Mac also check System Settings → Privacy & Security →
    > Microphone → Chrome. Then hold to talk again."
  - `NotFoundError` / `OverconstrainedError` → "No microphone was found."
  - anything else → the existing generic blocked message.
- Keep the same `onerror` `not-allowed` / `service-not-allowed` handling for
  mid-session revocation, pointing at the same Mac-aware message.

`usePushToTalk.ts` is unchanged (it already surfaces `error` upward, and
`ChatColumn` already funnels `speech.error` into the shared error banner).

### Out of code (must be flagged to the user)

The definitive unblock on the deployed site is **serve the frontend over
HTTPS** (reverse proxy + certificate) and **grant Chrome macOS mic permission**.
No frontend change can make the mic work over plain HTTP. This is called out
here so it is not mistaken for a code bug; it is not part of this
implementation's code changes.

---

## B. Colour disclaimer + final notes step

### Placement

A single new step inserted in `canvas_steps.REGISTRY` **between
`REWORK_CANVAS` and `REQUEST_QUOTE`** — i.e. after the customer reviews their
design (`REVIEW_DESIGN`, and any `REWORK_CANVAS` loop it opens) and before the
"Your design's ready to go" quote ask. First-unmet routing is by registry order,
so position in the tuple is the placement.

### New state

Add `ASK_FINAL_NOTES = "ask_final_notes"` to
`app.services.conversation.state_machine.ConversationState`. It is a brand-new
value used only by the v2 registry, so:

- It joins `V2_OWNED` automatically (derived from `REGISTRY`).
- v1 never routes to it (v1 has no reference to it).

### New `Step` record (`canvas_steps.py`)

```
Step(
    id=S.ASK_FINAL_NOTES,
    ask="{colour_note}",                       # rendered from store brand, below
    chips=(Chip("Nothing to add", {"final_notes_done": True}),),
    slots=("final_notes",),                    # free text only; see direct_capture
    direct_capture=True,                       # NEW flag — verbatim, no interpreter
    direct_answer=lambda m: {"final_notes": m.strip()},
    apply=_apply_final_notes,
    done_when=lambda c: bool(c.get("final_notes_done")),
)
```

Key properties:

- **Verbatim capture.** Per decision, the free text (which may be a Pantone/CMYK
  code or embroidery thread number) is taken **exactly as typed**, never
  reshaped by the LLM. A new `Step.direct_capture: bool` flag drives this
  (see the engine change below): on free text, the engine resolves via
  `step.direct_answer(message)` and skips the interpreter entirely.
- **`final_notes_done` is not a slot.** It is set only by the `"Nothing to add"`
  chip (trusted fields, merged directly) or by `_apply_final_notes` when notes
  were typed. Keeping it out of `slots` means it is **not** in `WRITABLE_SLOTS`,
  so the interpreter can never fabricate it on an earlier turn and silently skip
  the disclaimer.
- **`_apply_final_notes(c, f, s)`**: if `f.get("final_notes")` is non-empty,
  append `f"Customer final notes: {note}"` to `c["brief_notes"]` and set
  `c["final_notes_done"] = True`. (The chip path already set the flag via the
  merge before `apply` runs; the typed path sets it here.)
- **No canvas tool.** `tool` is `None`, so `directive_for` returns the
  all-tools-locked blob — correct, the design is finished.
- **Progress counter steady.** Add `S.ASK_FINAL_NOTES: S.ASK_PURPOSE` to
  `_PROGRESS_ANCHORS` and `S.ASK_FINAL_NOTES: 3` to `_STEP_SECTION`
  (section "Review"), matching `REVIEW_DESIGN`/`REQUEST_QUOTE`, so "Step X of N"
  does not grow past "done".

### Copy (`prompts.py`)

`V2_COLOUR_DISCLAIMER` — a template with `{name}`, `{embroidery_url}`,
`{print_url}` placeholders. Draft (refined at implementation):

> "One quick note before we send this over, {name} — screen colours aren't
> always exact. What you see is a guide; our team matches your design to the
> closest embroidery and print colours. Our reference charts: {embroidery_url}
> (embroidery) and {print_url} (print).
>
> If you already have a specific print colour (CMYK or Pantone) or an embroidery
> thread number, pop it below and we'll use it — otherwise we'll pick the
> closest match.
>
> Any final notes or pointers for the team? Type them here, or tap "Nothing to
> add"."

Copy must not promise exact colour matching — it explicitly says "closest
match" unless the customer supplies a code.

### Rendering the ask (store-configured links)

Mirror the existing `canvas_intro` threading. Important constraint:
`reply_for` runs a **single** `str.format` pass over `step.ask`, so a
`{name}` left inside a substituted `{colour_note}` value would **not** expand
(format does not recurse). Therefore the branding helper renders the disclaimer
**fully** — name and both URLs already substituted — and `reply_for` only drops
that finished string into `{colour_note}`.

- `branding.colour_disclaimer_text(store, name)` builds the fully-rendered
  string: reads `brand.colour_ref_embroidery_url` /
  `brand.colour_ref_print_url` (falling back to dummy defaults) and the passed
  `name`, and `.format`s `V2_COLOUR_DISCLAIMER` with all three. The returned
  string contains no remaining `{...}` placeholders.
- `orchestrator_v2.handle_message` and `handle_back` compute the display name
  the same way `reply_for` does (`collected.get("name") or "there"`) and call
  `colour_note = branding.colour_disclaimer_text(store, name)` alongside
  `intro = canvas_intro_text(store)`, passing `colour_note` into `reply_for`.
- `state_machine_v2.reply_for` gains one optional kwarg `colour_note: str = ""`,
  added to the `.format(...)` kwargs (alongside `name`, `persona`, `intro`).
  The `{colour_note}` placeholder appears only in this one step's `ask`, and its
  value has no braces, so every other step's formatting is unaffected and the
  single-pass format is correct.

### Engine change — verbatim `direct_capture` (`orchestrator_v2.handle_message`)

Add the `direct_capture` branch to the free-text handling:

```
fields = v2.resolve_chip(step, message, collected)
if fields is None and step.slots:
    if step.direct_capture:
        # The answer IS the message; no interpretation adds value and an LLM
        # could reshape a colour code. Still validated, still guarded by apply.
        fields = ie.validate_fields(step.direct_answer(message))
    else:
        try:
            fields = await ie.interpret_turn_v2(step, message, collected)
        except ie.LLMUnavailable:
            ...  # unchanged
        else:
            ack = await ie.write_ack(persona, fields)
elif fields is None:
    fields = {}
```

`direct_capture` steps produce no LLM `ack` (the next step is `REQUEST_QUOTE`,
whose "Your design's ready to go" copy is self-contained). This also means a
Haiku outage never strands this step.

### Admin-configurable links

Follow the exact `canvas_intro` pattern.

- **`branding.validate_brand`**: accept two new optional string keys
  `colour_ref_embroidery_url` and `colour_ref_print_url`. If present and
  non-empty, validate as `http(s)` URLs (reuse the `urlparse` scheme/netloc
  check from `_validate_menu_items`); empty/`None` → drop the key. Unknown keys
  remain preserved (existing behaviour).
- **Dummy defaults** in `prompts.py`:
  `V2_DEFAULT_COLOUR_EMBROIDERY_URL = "https://example.com/embroidery-chart"`
  and `V2_DEFAULT_COLOUR_PRINT_URL = "https://example.com/print-colour-guide"`
  (neutral placeholders — obviously replaceable in admin).
- **`BrandingView.tsx`**: two URL text inputs under the "Canvas intro" section,
  labelled "Embroidery colour chart URL" and "Print colour guide URL", wired via
  the existing `setField`. Add the two keys to the `Brand` type
  (`frontend/src/lib/types.ts`). Client-side validation mirrors the server
  (`/^https?:\/\//i`, allow empty).

### Chat link rendering (linkify)

Assistant bubbles in `ChatColumn.tsx` render as `whitespace-pre-wrap` plain
text, so URLs would not be clickable. Add a small linkifier to the assistant
message bubble: split `content` on an `http(s)://…` regex and render matched
URLs as `<a href={url} target="_blank" rel="noopener noreferrer">`. Self-
contained, benefits the whole chat, no external dependency.

---

## Testing

Backend (all deterministic — pure `done_when`/routing, no LLM, no Supabase):

- `next_step` returns `ASK_FINAL_NOTES` once every prior step is done and
  before `REQUEST_QUOTE`; and returns `REQUEST_QUOTE` after `final_notes_done`.
- `_apply_final_notes` appends typed notes to `brief_notes` and sets the flag;
  the `"Nothing to add"` chip sets the flag with no brief note.
- The interpreter cannot set `final_notes_done` (`final_notes_done` not in
  `WRITABLE_SLOTS`).
- `direct_capture` path: free text is banked verbatim without calling the
  interpreter (assert `interpret_turn_v2` is not awaited).
- `branding.validate_brand` accepts valid http(s) link keys, rejects non-URLs,
  drops empties; `colour_disclaimer_text` uses store links when set and dummy
  defaults otherwise.
- An e2e walk (the v2 chip-driven walk) reaches `ASK_FINAL_NOTES` and then
  `REQUEST_QUOTE` with `interpret_turn_v2` raising `LLMUnavailable` throughout
  (proving the new step needs no model).

Frontend:

- `useSpeechRecognition`: insecure-context short-circuit sets the https message
  and does not call `getUserMedia`; `getUserMedia` rejection with
  `NotAllowedError` sets the Mac-aware message.
- Message-bubble linkifier renders `<a>` for URLs, leaves plain text alone.
- `BrandingView` renders and persists the two new URL fields; client validation
  rejects a non-http value.

Run baseline with `CANVAS_ORCHESTRATOR_V2=false pytest -q`; run the new tests
(and the e2e walk) with the flag on. Frontend: targeted `vitest run` on the
touched files (full run is flaky on this Windows host).

## Out of scope

- HTTPS/reverse-proxy setup for prod (environmental; flagged, not built).
- Any change to v1 flows, the render pipeline, or the quote email content.
- Per-store override of the disclaimer body copy (only the two links are
  configurable; the surrounding copy is fixed).
