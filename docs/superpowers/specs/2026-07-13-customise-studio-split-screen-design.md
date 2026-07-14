# Customise Studio — Split-Screen (Canvas + Chat) Design

**Date:** 2026-07-13
**Status:** Approved (design), pending implementation plan
**Branch:** `feat/canvas-design-studio`

## 1. Summary

Replace the current two-step canvas experience — the 3-column `DesignStudio`
(design only, no chat) that *hands off* to a full-screen `ChatPanel` after
"See it rendered" — with a **single combined screen** for canvas sessions:

- **LEFT** — the full interactive canvas studio (face thumbnails · Konva canvas ·
  selected-element toolbar · tool rail), unchanged in behaviour.
- **RIGHT** — a live chat column, visible from the start of the session and
  present throughout, wired to the existing `chatStore`.

Designing and chatting coexist on one screen. "See it rendered" → verify email →
deliver → refine all continue in the right-hand chat panel; there is **no
full-screen `ChatPanel` navigation** for canvas sessions anymore.

This is a **layout / composition** change. The question-and-chat **orchestration**
(what the assistant asks, when, and how it reacts to canvas edits) is explicitly
**out of scope** and will be reworked in a later pass. This spec only guarantees
that the existing chat states (verify → deliver → refine) keep working visually
in the new right panel.

## 2. Goals

- One screen: tools/canvas on the left, chat on the right, for the whole canvas
  session.
- Reuse the existing chat UI (bubbles, typing indicator, chips, text input,
  voice) driven by `chatStore` — no behaviour rewrite now.
- Keep all current canvas design logic (flatten → upload layouts → finalize)
  untouched.
- Isolate the two halves so the later orchestration rewrite touches only the
  chat column + `chatStore`, not the canvas.

## 3. Non-Goals

- Rewriting the conversation flow / question orchestration (later pass).
- Changing the customise/blank chat Q&A flows for non-canvas sessions —
  `ChatPanel` stays as-is for those.
- Changing generation, delivery, or backend pipeline.
- Pin annotation and other retired/hidden states — not reintroduced here.

## 4. Architecture

New top-level component **`CustomiseStudio`** composes two reusable pieces and is
rendered by `App.tsx` for canvas sessions (`sessionView === 'canvas'`), replacing
the current `DesignStudio`-then-`ChatPanel` path.

```
CustomiseStudio
├── LEFT  → DesignStudioSurface   (today's DesignStudio internals, extracted:
│                                   face thumbnails · canvas · selected toolbar ·
│                                   tool rail · flatten→layouts→finalize logic)
└── RIGHT → ChatColumn            (ChatPanel's chat half, extracted:
                                    message list · typing indicator · chips ·
                                    text input · voice — driven by chatStore)
```

### 4.1 DesignStudioSurface

- Extracted from the current `DesignStudio` (`components/DesignStudio/index.tsx`)
  **internals**: the `<CanvasStage>` + `<SelectedToolbar>` + `<FaceThumbnails>` +
  `<ToolRail>` composition and all their handlers (`handleUpload`, `addGraphic`,
  `doRender`, seeding face backgrounds, colourways, `GraphicsPicker`).
- Keeps its existing **internal 3-column** structure (thumbs / canvas+toolbar /
  tool rail) exactly as today — it just lives inside a `flex-1` column now
  instead of occupying the full width.
- **Removes** its own top-level `<header>` (moves to `CustomiseStudio`) and the
  **email modal** — email is captured inline in the chat, so `onRenderClick`
  calls `doRender()` directly.
- **`doRender()` change:** on success it no longer calls `setView({view:'session'})`
  to navigate to `ChatPanel`. Instead it hydrates the chat store in place
  (`useChatStore.getState().hydrate([], res.state, res.data)`) so the right-hand
  `ChatColumn` — already mounted — picks up the post-finalize state
  (verify/deliver/refine). The screen does not change; only the chat updates.

### 4.2 ChatColumn

- Extracted from `ChatPanel`'s right-hand chat half: the scrolling message list,
  `TypingIndicator`, option/refine chips, the bottom input panel (text +
  push-to-talk voice + send), and the inline special states still needed for the
  canvas flow (e.g. inline email capture / verification). Driven by `chatStore`
  and `generationStore` exactly as `ChatPanel` is today.
- Does **not** include `ChatPanel`'s left `ProductViewer` half or its own header —
  those responsibilities move to the canvas surface and the shared header.
- Extraction is deliberately **light**: because the orchestration is being
  reworked, we port the visual pieces and the states the canvas flow actually
  reaches (verify → deliver → refine), not every legacy special state.

### 4.3 ChatPanel (unchanged)

`ChatPanel` remains the screen for **non-canvas** sessions (`sessionView ===
'session'`, the old customise/blank Q&A flows). It is not deleted and not
refactored to depend on `ChatColumn` in this pass (avoids risk); shared visual
drift between the two is acceptable for now and reconciled during the later
orchestration rewrite.

### 4.4 App routing

`App.tsx`: `sessionView === 'canvas'` renders `<CustomiseStudio />` instead of
`<DesignStudio />`. The `DesignStudio` component is superseded by
`CustomiseStudio` + `DesignStudioSurface`; keep the old file only if still
referenced elsewhere, otherwise remove it as part of the extraction.

## 5. Layout

### Desktop (`md` and up)

Full-height screen: shared header on top, two panels below.

```
┌─────────────────────────────────────────────────────────────────────┐
│  MAD HATS   ·  <product name> › Design                        header │
├──────────────────────────────────────────────┬──────────────────────┤
│  LEFT — DesignStudioSurface  (flex-1, min-w-0)│  RIGHT — ChatColumn   │
│ ┌──────┬───────────────────────┬───────────┐ │  (w-[380px], shrink-0,│
│ │thumbs│        canvas         │ tool rail │ │   border-l)           │
│ │ rail │   [selected toolbar]  │  +Text …  │ │ ┌──────────────────┐  │
│ └──────┴───────────────────────┴───────────┘ │ │ message list      │  │
│                                               │ │ (scrolls)         │  │
│                                               │ ├──────────────────┤  │
│                                               │ │ input · 🎤 · send │  │
└───────────────────────────────────────────────┴──────────────────────┘
```

- Outer: `flex flex-col h-screen bg-base`.
- Body: `flex-1 flex min-h-0`.
- Left: `flex-1 min-w-0` (keeps the existing internal 3-column; scrollable so it
  never clips when the chat consumes horizontal space).
- Right: `w-[380px] shrink-0 border-l border-border flex flex-col min-h-0`.

### Mobile (below `md`)

Stack vertically (matches how both existing screens already collapse):
`flex-col` — canvas surface on top, chat below. Chat gets a capped height
(`h-[45vh]`) so both halves stay reachable.

### Header

Single shared bar — the one currently in `DesignStudio` (MAD HATS wordmark +
`<product name> › Design`). `ChatPanel`'s header is not used on this screen.

## 6. Error handling

- Canvas surface keeps its existing inline error banner (upload / render
  failures) shown above/within the left panel.
- Chat errors surface through `chatStore` as they do today.

## 7. Testing

- **Unit (vitest):** `CustomiseStudio` renders both panels; `DesignStudioSurface`
  renders canvas + tool rail; `ChatColumn` renders messages from a seeded
  `chatStore` and the input.
- **Behaviour:** `doRender()` success hydrates `chatStore` (verify state) and does
  **not** change `sessionView` away from `canvas`.
- **Regression:** non-canvas sessions still render `ChatPanel`; existing
  `ChatPanel` / canvas store tests stay green (`vitest run`, currently 181).
- **Manual:** in-browser canvas session — design on left, chat visible on right
  from start; "See it rendered" → email verify → delivery → refine all occur in
  the right panel with the canvas still shown.

## 8. Out-of-scope follow-ups

- Question/chat orchestration rewrite (what the assistant asks and how it reacts
  to canvas edits).
- Optionally refactor `ChatPanel` to reuse `ChatColumn` once orchestration
  settles.
