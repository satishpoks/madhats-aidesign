# Frontend Light-Theme Redesign — Design

> Date: 2026-07-02
> Scope: Full light re-skin + layout polish of the active chat studio frontend, plus a hold-SPACEBAR push-to-talk voice control.

---

## 1. Goal

Re-theme the active React frontend from its current **dark** look to a **light** theme that matches the MadHats Figma design language, polish the placement of images/buttons/panels, and replace the click-to-toggle microphone with a **hold-spacebar push-to-talk** voice control (with a press-and-hold mic button retained for touch/mouse).

Figma reference: `01 — Shopify Widget` page of
`https://www.figma.com/design/fFPXYD7eIJPSo47tUPjK2r/MadHats-AI-Design-Studio-—-Wireframes---Screens`
(file key `fFPXYD7eIJPSo47tUPjK2r`). That page documents the widget button + tracking URL, not the studio itself, but defines the visual language: white cards on a very light gray canvas, subtle gray borders, dark-navy text, the existing MadHats orange accent (often with a gold ✨ sparkle), and a dark-navy bar reserved for strong elements (the Shopify nav and "Add to Cart").

## 2. Key Insight — token-driven

The frontend already consumes **semantic Tailwind tokens** everywhere (`bg-base`, `bg-surface`, `bg-surfaceAlt`, `border-border`, `text-textPrimary`, `text-textSub`, `text-textMuted`, `accent`, `accentHover`). So the dark→light flip is primarily a **token redefinition** in `tailwind.config.js`, after which every component follows. Remaining work is per-component placement polish and fixing the few spots that bypass tokens:

- `index.css` — the `.shimmer` gradient uses hardcoded dark hex values.
- `ApiProductPicker` — one `hover:shadow-[0_0_0_1px_#FF5C00]` (fine to keep — it's the accent) and dark-tinted skeletons.
- Error banners in `ChatPanel` use dark-mode utility classes (`bg-red-950/40`, `text-red-300`, `border-red-800`) that must move to light equivalents.

**Approach chosen:** redefine tokens + polish. Rejected alternatives: a dual-theme `data-theme` toggle (more infra than needed now — YAGNI), and per-component hardcoded light colors (discards the token system).

## 3. Light Palette

| Token | Dark (current) | Light (new) | Use |
|---|---|---|---|
| `base` | `#0F0F11` | `#F7F8FA` | app canvas / page background |
| `surface` | `#1A1A1F` | `#FFFFFF` | cards, assistant bubbles, inputs |
| `surfaceAlt` | `#222228` | `#EEF0F4` | image placeholders, subtle fills |
| `border` | `#2A2A35` | `#E5E7EB` | all borders |
| `accent` | `#FF5C00` | `#FF5C00` (unchanged) | primary orange CTA |
| `accentHover` | `#E64F00` | `#E64F00` (unchanged) | orange hover |
| `textPrimary` | `#F5F5F5` | `#1A1D29` | primary text (navy near-black) |
| `textSub` | `#9A9AA8` | `#4B5563` | secondary text |
| `textMuted` | `#6B6B7B` | `#8A90A0` | hints / muted labels |
| `ink` **(new)** | — | `#1E2130` | dark-navy header bar (echoes Figma nav) |

`index.css` `.shimmer` gradient recolored to light grays (e.g. `#EEF0F4` → `#F7F8FA` → `#EEF0F4`).

## 4. Layout & Placement Polish

### Header (both ChatPanel and ApiProductPicker)
Dark-navy `ink` bar with the orange **"MadHats"** wordmark, a `|` divider, "AI Design Studio", and a "Beta Preview" pill on the right. White/light text on navy — mirrors the Figma Shopify nav bar and anchors the otherwise-light layout.

### ChatPanel (two-pane layout kept)
- **Left — ProductViewer:** main product image centered in a white bordered card; thumbnail strip below. Mostly token-driven already; verify contrast on light.
- **Right — chat column:**
  - User bubbles: orange background, white text, `rounded-br-sm`.
  - Assistant bubbles: white surface, navy text, gray border, `rounded-bl-sm`.
  - Option chips (`options`, `options2`): white pills with border; hover → orange border + orange text.
  - "Continue" affordance: white pill with orange border; hover fills orange.
  - `TypingIndicator` dots and `GenerationPanel` spinner recolored for light (muted-gray dots, orange spinner, green ✓ unchanged).
  - Error banner → light style: `bg-red-50`, `border-red-200`, `text-red-700`.
- **Composer:** white input, orange **Send**, and the voice control (§5). Persistent subtle hint near composer: "Hold space to talk".

### Sub-panels
- `LogoUploader`, `PinAnnotator`: light surfaces via tokens. Pins stay orange (pending) / green (saved) with a white ring so they read on any background. Pin input error text → light red.
- `GenerationPanel`: light surface, orange spinner, green ✓; reassurance copy unchanged.

### ApiProductPicker (dev entry)
Light hero, white product cards with gray border and orange hover ring, light skeletons. Keep the accent-colored hover shadow.

### Retired old studio screens
`StudioCanvas`, `RefineScreen`, `WornScreen`, `ConceptModal`, `ProductPicker` are off the active path. They inherit the new tokens automatically; **no dedicated polish** — out of scope.

## 5. Voice — Hold-SPACEBAR Push-to-Talk

Extend the existing `useSpeechRecognition` hook (or add a thin `usePushToTalk` wrapper around it) so the studio supports walkie-talkie style voice:

- **Global key listener:** `keydown` Space → `start()`, `keyup` Space → `stop()`. `stop()` finalizes recognition, which fires `onend`/`onresult` and sends the transcript as a chat turn (existing behavior).
- **Guards (must all hold):**
  - Ignore Space when the active element is an `input`, `textarea`, `select`, or `[contenteditable]` — so typing spaces never triggers the mic.
  - Ignore Space when the active element is a `button` (Space activates buttons) — avoid double-firing.
  - Ignore auto-repeat `keydown` (`event.repeat`) so a held key starts recognition exactly once.
  - No-op entirely when `speech.supported` is false (Firefox, jsdom) — fall back to typed input.
  - `preventDefault()` on the handled Space to stop the page from scrolling.
- **Mic button (retained, redesigned):** press-and-hold via `pointerdown`/`pointerup`/`pointerleave` for touch/mouse; still usable as a toggle where hold isn't practical. Disabled while `sending`.
- **Feedback:** while listening, mic button shows a pulsing "🎤 Listening… release space to send" state and the input placeholder reads "Listening…". A persistent muted hint "Hold space to talk" sits under/near the composer when speech is supported.

## 6. Testing (TDD)

Frontend uses `vitest` (`npx vitest run`). Existing suites: `ChatPanel.test.tsx`, `ApiProductPicker.test.tsx`, `api.test.ts`, `sessionStore.test.ts`.

- **New:** push-to-talk behavior test —
  - `keydown` Space with no field focused → `start()` called once (even with a second repeat event).
  - `keyup` Space → `stop()` called.
  - Space while an `input`/`button` is focused → `start()` **not** called.
  - When speech unsupported → listener is a no-op.
- **Keep green:** existing suites; update any assertions that pin dark color classes to the new light classes.

## 7. Files Touched

- `frontend/tailwind.config.js` — light token values + new `ink` token.
- `frontend/src/index.css` — light `.shimmer` gradient.
- `frontend/src/hooks/useSpeechRecognition.ts` — push-to-talk / spacebar support (or new `usePushToTalk.ts`).
- `frontend/src/components/ChatPanel/index.tsx` — header, bubbles, chips, composer, voice UI, error banner, sub-panels.
- `frontend/src/components/ProductViewer/index.tsx` — light polish (mostly token-driven).
- `frontend/src/components/ApiProductPicker/index.tsx` — header, hero, cards, skeletons.
- `frontend/src/__tests__/` — new push-to-talk test; adjust existing color-class assertions if any.

## 8. Constraints & Non-Goals

- No backend changes. The server-rendered quote page (`GET /quote/{token}`) is out of scope.
- Generated design still delivered by email only — the viewer keeps showing blank product angles, never the preview. Copy unchanged.
- No new dependencies. Web Speech API remains the STT source; graceful degradation preserved.
- Keep the existing conversation/generation data flow untouched — this is purely presentation + input UX.
