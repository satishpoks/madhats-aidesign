# Customise Studio — Split-Screen (Canvas + Chat) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two-step canvas experience (design-only `DesignStudio` → full-screen `ChatPanel` handoff) with a single split screen for canvas sessions: full canvas studio on the left, live chat on the right.

**Architecture:** A new `CustomiseStudio` screen composes two pieces side by side — `DesignStudioSurface` (today's `DesignStudio` internals, minus its header/email-modal, with `doRender` hydrating the chat store in place instead of navigating) and `ChatColumn` (a self-contained reuse of `ChatPanel`'s chat half, driven by `chatStore`). `App.tsx` renders `CustomiseStudio` for `sessionView === 'canvas'`. `ChatPanel` is left untouched for the old non-canvas flows.

**Tech Stack:** React 18, TypeScript, Vite, Tailwind, Zustand, react-konva; tests via Vitest + Testing Library.

## Global Constraints

- Frontend package manager is **npm**; tests run with `npx vitest run` (never `npm test` — that's watch mode and hangs). Typecheck/build with `npm run build`.
- **Do NOT modify** `frontend/src/components/ChatPanel/index.tsx` or its test `frontend/src/__tests__/ChatPanel.test.tsx`. `ChatPanel` remains the screen for non-canvas sessions. Extraction is by copy, not by refactoring ChatPanel to depend on the new component (spec §4.3 — avoids risk).
- **react-konva does not render in this jsdom test env** (no `canvas` package/mock — that's why `DesignStudio` has no test). Never write a unit test that fully renders `CanvasStage`, `DesignStudioSurface`, or an un-mocked `CustomiseStudio`; those are verified by typecheck/build, by composition tests with **mocked** children, and by manual browser check.
- The design is email-gated: the on-screen design is only revealed after email verification + completed generation. Do not change that gating.
- Existing suite baseline: `npx vitest run` = 181 passing (2 pre-existing `adminQuotes` failures unrelated). Keep it green (aside from those 2).

---

## File Structure

**Create:**
- `frontend/src/components/CustomiseStudio/ChatColumn.tsx` — self-contained reusable chat column (message list · chips · input · voice · special-state panels), driven by `chatStore`/`generationStore`. **No auto-kickoff**; shows an empty-state hint until the store is hydrated.
- `frontend/src/components/CustomiseStudio/index.tsx` — `CustomiseStudio` screen shell: shared header + responsive two-pane (`DesignStudioSurface` left, `ChatColumn` right).
- `frontend/src/components/DesignStudio/Surface.tsx` — `DesignStudioSurface`: today's `DesignStudio` internals minus header + email modal; `doRender` hydrates chat in place (no navigation).
- `frontend/src/__tests__/ChatColumn.test.tsx` — unit tests for `ChatColumn`.
- `frontend/src/__tests__/CustomiseStudio.test.tsx` — composition test (mocked children).

**Modify:**
- `frontend/src/App.tsx` — render `<CustomiseStudio />` for `sessionView === 'canvas'`; drop the `DesignStudio` import.

**Delete:**
- `frontend/src/components/DesignStudio/index.tsx` — superseded by `Surface.tsx` (only `App.tsx` imported it). The sibling files (`CanvasStage.tsx`, `ToolRail.tsx`, `SelectedToolbar.tsx`, `FaceThumbnails.tsx`, `GraphicsPicker.tsx`, `nodes.tsx`) stay.

---

## Task 1: ChatColumn — self-contained reusable chat column

**Files:**
- Create: `frontend/src/components/CustomiseStudio/ChatColumn.tsx`
- Test: `frontend/src/__tests__/ChatColumn.test.tsx`

**Interfaces:**
- Consumes: `useSessionStore` (`sessionId`, `productRef`), `useChatStore` (all selectors listed below), `useGenerationStore` (`startGeneration`, `startRegeneration`, `designs`, `status`), `usePushToTalk` hook, `uploadLogo`/`postComposite` from `../../lib/api`, `Modal` from `../Modal`.
- Produces: `export function ChatColumn(): JSX.Element` — takes **no props**, reads everything from stores. Renders a full-height flex column intended to sit inside a fixed-width right panel.

**Extraction source:** `frontend/src/components/ChatPanel/index.tsx`. Copy the helper components and the right-column body from there, with the exact modifications below. This is a faithful copy of working code — do not "improve" it.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/ChatColumn.test.tsx`. Mirror the mock/seed pattern from `ChatPanel.test.tsx` (lines 1–117): mock `../lib/api`, seed `useSessionStore`/`useChatStore`/`useGenerationStore` in `beforeEach`.

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn().mockResolvedValue({ reply: 'ok', state: 'ask_name', data: {} }),
  createSession: vi.fn(),
  fetchProducts: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 24, offset: 0 }),
  fetchProduct: vi.fn(),
  uploadLogo: vi.fn().mockResolvedValue({ asset_url: 'u', asset_hash: 'h' }),
  addPin: vi.fn(),
  generatePreview: vi.fn().mockResolvedValue({ job_id: 'j' }),
  generationStatus: vi.fn().mockResolvedValue({ status: 'complete', image_url: 'i', watermarked_url: 'w' }),
  createLead: vi.fn(),
  sendVerify: vi.fn(),
  postComposite: vi.fn().mockResolvedValue({ views: {} }),
  pollVerification: vi.fn().mockResolvedValue({ verified: false }),
  pollRegeneration: vi.fn(),
  pollGenerationAdvance: vi.fn(),
}))

import { sendChat } from '../lib/api'
import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import { useGenerationStore } from '../store/generationStore'
import { ChatColumn } from '../components/CustomiseStudio/ChatColumn'

function seed() {
  useSessionStore.setState({
    sessionId: 'sess-1', shareToken: 't', state: 'greeting',
    productRef: {
      id: 'p1', name: 'Classic Snapback', colour: 'Black', style: 'snapback',
      reference_image_url: 'https://example.com/cap.jpg', view_images: {},
    },
    entryContext: null, view: 'canvas',
  })
  useChatStore.setState({
    messages: [], chatState: '', options: [], options2: [],
    triggerGeneration: false, continuable: false, tintReady: false, tintHex: '',
    colourSwatches: [], colourPicker: false, sending: false, chatError: null,
    kickoffDone: false,
  })
  useGenerationStore.getState().reset()
}

beforeEach(() => { vi.clearAllMocks(); seed() })

describe('ChatColumn', () => {
  it('does NOT auto-kickoff on mount (canvas activates chat via finalize/hydrate)', async () => {
    render(<ChatColumn />)
    // give effects a tick
    await new Promise(r => setTimeout(r, 0))
    expect(vi.mocked(sendChat)).not.toHaveBeenCalled()
  })

  it('renders an empty-state hint when there are no messages', () => {
    render(<ChatColumn />)
    expect(screen.getByText(/design.*chat|chat.*here|render/i)).toBeInTheDocument()
  })

  it('renders hydrated messages', () => {
    useChatStore.setState({
      messages: [{ id: 'm1', role: 'assistant', text: 'Your design is on its way' }],
      chatState: 'offer_refine', kickoffDone: true,
    })
    render(<ChatColumn />)
    expect(screen.getByText('Your design is on its way')).toBeInTheDocument()
  })

  it('sends a chip click through chatStore.sendMessage', async () => {
    useChatStore.setState({
      messages: [{ id: 'm1', role: 'assistant', text: 'Pick one' }],
      options: ['Yes', 'No'], chatState: 'offer_refine', kickoffDone: true,
    })
    render(<ChatColumn />)
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }))
    await waitFor(() => expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-1', 'Yes'))
  })

  it('sends typed input on submit', async () => {
    useChatStore.setState({ chatState: 'offer_refine', kickoffDone: true })
    render(<ChatColumn />)
    fireEvent.change(screen.getByPlaceholderText(/type your message/i), { target: { value: 'hello' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Send' }).closest('form')!)
    await waitFor(() => expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-1', 'hello'))
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/ChatColumn.test.tsx`
Expected: FAIL — `Failed to resolve import '../components/CustomiseStudio/ChatColumn'`.

- [ ] **Step 3: Create ChatColumn.tsx**

Create `frontend/src/components/CustomiseStudio/ChatColumn.tsx`. Build it by copying from `ChatPanel/index.tsx` with these exact rules:

1. **Imports** (top of file):
```tsx
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useSessionStore } from '../../store/sessionStore'
import { useChatStore } from '../../store/chatStore'
import { useGenerationStore } from '../../store/generationStore'
import { Modal } from '../Modal'
import { usePushToTalk } from '../../hooks/usePushToTalk'
import { uploadLogo, postComposite } from '../../lib/api'
```
(Note: drop `ProductViewer`, `addPin`, and the `PinAnnotator` — those belong to ChatPanel's left panel, which is NOT part of the chat column.)

2. **Helper components** — copy verbatim into this file (they are module-scoped in ChatPanel):
   - `TypingIndicator` — `ChatPanel/index.tsx` lines **14–35**.
   - `LogoUploader` (+ its `LogoUploaderProps`) — `ChatPanel/index.tsx` lines **41–120** (the full component; copy through its closing `}`. It uses `uploadLogo` only).
   - `GenerationPanel` — the generation/preview status panel, `ChatPanel/index.tsx` lines **295–322** (the component reading `useGenerationStore` status and rendering the spinner / "design is ready" reassurance). Copy verbatim.
   - **Do NOT** copy `PinAnnotator` (`ChatPanel/index.tsx` lines **135–293** — it renders the left-panel pin UI, not part of the chat column).

3. **Component body** — `export function ChatColumn()`:
   - Copy the store selectors and local state from `ChatPanel` lines **330–433**, **EXCEPT** omit anything only used by the left ProductViewer/pin panel: you still need `sessionId`, `productRef`, all `useChatStore` selectors, all `useGenerationStore` selectors, `composite` state + its effect (lines 399–417 — the colour-swatch/composite chips in the bottom panel use it), `inputText`, `customColour`, `logoModalDismissed`, `messagesEndRef`, `inputRef`, `wasSendingRef`. Keep `designReleased`/`awaitingVerification`/`compositePreview` derivations (lines 361–393) — cheap, and `compositePreview` gates a bottom-panel block.
   - **Effects — copy these from ChatPanel:** generation trigger+advance (lines 445–452), regeneration (458–465), verification poll (470–476), auto-scroll (479–481), focus-after-send (487–493), logo-modal reset (431–433), speech-error surfacing (525–527).
   - **Effect to OMIT:** the kickoff effect (ChatPanel lines 436–440). ChatColumn must NOT auto-kickoff — the canvas flow seeds the conversation through `finalizeCanvas` → `chatStore.hydrate()` (which sets `kickoffDone: true`). Do not import or call `kickoff`.
   - Copy handlers `handleSubmit` (499–505), `handleChip` (507–510), the `speech = usePushToTalk(...)` block (516–521), and `const isStatementOnly = continuable && !sending` (529).

4. **Return JSX** — return ONLY the chat column subtree (no outer screen, no app header). Structure:
```tsx
  return (
    <div className="flex flex-col min-h-0 h-full">
      {/* Chat header — ChatPanel lines 583–598 (Ricardo identity + Step X of N) */}
      {/* Error banner — ChatPanel lines 603–617 */}

      {/* Message list — ChatPanel lines 622–643, BUT wrap the empty case: */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 flex flex-col gap-3 min-h-0">
        {messages.length === 0 && !sending && (
          <p className="m-auto max-w-xs text-center text-sm text-textMuted">
            Design your cap on the left. Once you hit “See it rendered”, we’ll chat with you here to finish up and send it over.
          </p>
        )}
        {messages.map(msg => ( /* ...verbatim from lines 623–638... */ ))}
        {sending && <TypingIndicator />}
        <div ref={messagesEndRef} />
      </div>

      {/* Bottom panel — ChatPanel lines 648–864 verbatim (special states, chips,
          colour swatches, composite grid, continue, voice, input form) */}
    </div>
  )
```
Copy the chat header, error banner, message list rows, and the entire bottom panel **verbatim** from the referenced ChatPanel line ranges. The only additions/changes vs ChatPanel are: (a) the outer wrapper class shown above (was `flex-1 md:w-1/2 flex flex-col min-h-0` in ChatPanel — replace with `flex flex-col min-h-0 h-full`), and (b) the empty-state `<p>` block shown above.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/ChatColumn.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npm run build`
Expected: build succeeds (no TS errors). Fix any unused-import errors by removing selectors/imports you copied but don't use.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/CustomiseStudio/ChatColumn.tsx frontend/src/__tests__/ChatColumn.test.tsx
git commit -m "feat(canvas): extract reusable ChatColumn from ChatPanel (no auto-kickoff)"
```

---

## Task 2: DesignStudioSurface — canvas studio without header/handoff

**Files:**
- Create: `frontend/src/components/DesignStudio/Surface.tsx`
- Delete: `frontend/src/components/DesignStudio/index.tsx` (after moving logic)

**Interfaces:**
- Consumes: `useSessionStore`, `useCanvasStore`, `useChatStore`, `CanvasStage`, `ToolRail`, `SelectedToolbar`, `FaceThumbnails`, `GraphicsPicker`, `Modal`, `flattenStage`/`dataUrlToFile`, `uploadLogo`/`uploadCanvasLayouts`/`finalizeCanvas`, `loadImage` — all as `DesignStudio/index.tsx` imports them today.
- Produces: `export function DesignStudioSurface(): JSX.Element` — no props. Renders the three internal columns (thumbnails / canvas+toolbar / tool rail) **without** the app header. On successful render it hydrates `chatStore` in place; it does NOT change `sessionView`.

- [ ] **Step 1: Create Surface.tsx by copying index.tsx**

Copy the entire current `frontend/src/components/DesignStudio/index.tsx` into a new `frontend/src/components/DesignStudio/Surface.tsx`, renaming the exported function `DesignStudio` → `DesignStudioSurface`. Keep all imports, refs, state, `useEffect` seeding, `handleUpload`, `addGraphic`, `doRender`, `onRenderClick`.

- [ ] **Step 2: Remove the app header, outer screen chrome, AND the email modal**

Spec §4.1: on this screen the email modal is **retired** — the chat (right panel) captures the email inline after render via the backend's `ASK_EMAIL` fallback (reached because `finalizeCanvas` is called with no email; `advance_after_generation` then routes `generating → ask_email`). So:
- Delete the email state and modal: remove `emailOpen`/`setEmailOpen`, `email`/`setEmail`, the `onRenderClick` function, and the `<Modal open={emailOpen} …>` block. Remove the `Modal` import **only if** it's now unused (it is — `GraphicsPicker` is its own component).
- The tool rail's render button now calls `doRender` directly (`onRender={() => void doRender()}`).

In `Surface.tsx`, change the top-level return so it renders only the studio body (no `<header>`, no full-screen `h-screen` wrapper — the parent `CustomiseStudio` owns those). Replace the outer `return (<div className="h-screen bg-base flex flex-col"> … </div>)` structure with:

```tsx
  return (
    <div className="flex-1 flex flex-col min-h-0">
      {error && (
        <div role="alert" className="mx-4 mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex-1 flex flex-col md:flex-row min-h-0">
        {/* Left rail — face-thumbnail navigator */}
        <div className="md:border-r border-border overflow-y-auto flex-shrink-0">
          <FaceThumbnails />
        </div>

        {/* Centre — canvas + contextual toolbar */}
        <div className="flex-1 flex flex-col items-center gap-3 p-4 overflow-auto min-w-0">
          <CanvasStage stageRef={stageRef} />
          <SelectedToolbar />
        </div>

        {/* Right rail — tools + render */}
        <div className="md:border-l border-border overflow-y-auto flex-shrink-0">
          <ToolRail onAddText={() => addText('Your text')} onUploadClick={() => fileRef.current?.click()}
            onGraphicsClick={() => setGraphicsOpen(true)}
            colourways={colourways} onRender={() => void doRender()} rendering={rendering} />
        </div>
      </div>

      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={handleUpload} className="sr-only" aria-label="Upload image" />

      <GraphicsPicker open={graphicsOpen} onClose={() => setGraphicsOpen(false)}
        onPickShape={kind => addShape(kind)} onPickImage={url => void addGraphic(url)} />
    </div>
  )
```

Remove the now-unused `productRef`-in-header reference (the `productRef` binding is still needed for the seeding effect — keep the `const productRef = useSessionStore(...)` line, just drop the header JSX that displayed its name). Also remove the now-unused `email`, `emailOpen`, `onRenderClick`, and `Modal` symbols.

- [ ] **Step 3: Change `doRender` to hydrate in place (no navigation)**

In `Surface.tsx` `doRender`, the success branch currently does:
```tsx
      useChatStore.getState().hydrate([], res.state, res.data)
      setView({ view: 'session' })
```
Change it to hydrate only — the `ChatColumn` is already mounted in the same screen, so there is no navigation:
```tsx
      // Chat lives in the right panel of this same screen — hydrate it in place;
      // do NOT navigate away (that was the old full-screen ChatPanel handoff).
      useChatStore.getState().hydrate([], res.state, res.data)
```
Delete the `const setView = useSessionStore.setState` binding and its usage (no longer needed). Update the adjacent comment ("Hand off to the existing ChatPanel…") to reflect the in-place hydrate. Since the email modal is gone, also change the `finalizeCanvas` call to pass no email (the chat asks for it after generation):
```tsx
      const res = await finalizeCanvas(sessionId, { canvas_design: design })
```

- [ ] **Step 4: Delete the old index.tsx and verify nothing else imports it**

Delete `frontend/src/components/DesignStudio/index.tsx`.

Run: `cd frontend && npx tsc --noEmit` (or `npm run build`).
Expected: it FAILS only in `App.tsx` (`Cannot find module './components/DesignStudio'`) — that import is repointed in Task 3. No other file should reference it. If any other file errors, that's a real missing dependency — resolve it.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DesignStudio/Surface.tsx
git rm frontend/src/components/DesignStudio/index.tsx
git commit -m "refactor(canvas): DesignStudioSurface — studio body, hydrate chat in place, no nav"
```
(The build is intentionally red between Task 2 and Task 3; Task 3 makes it green.)

---

## Task 3: CustomiseStudio screen + App wiring

**Files:**
- Create: `frontend/src/components/CustomiseStudio/index.tsx`
- Test: `frontend/src/__tests__/CustomiseStudio.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `DesignStudioSurface` from `../DesignStudio/Surface`, `ChatColumn` from `./ChatColumn`, `useSessionStore` (`productRef`).
- Produces: `export function CustomiseStudio(): JSX.Element` — the full-height canvas screen. `App.tsx` renders it for `sessionView === 'canvas'`.

- [ ] **Step 1: Write the failing composition test (mocked children — avoids Konva)**

Create `frontend/src/__tests__/CustomiseStudio.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Mock both heavy children so the screen renders without react-konva or store wiring.
vi.mock('../components/DesignStudio/Surface', () => ({
  DesignStudioSurface: () => <div data-testid="surface" />,
}))
vi.mock('../components/CustomiseStudio/ChatColumn', () => ({
  ChatColumn: () => <div data-testid="chat-column" />,
}))

import { useSessionStore } from '../store/sessionStore'
import { CustomiseStudio } from '../components/CustomiseStudio'

beforeEach(() => {
  useSessionStore.setState({
    sessionId: 'sess-1', shareToken: 't', state: 'greeting',
    productRef: {
      id: 'p1', name: 'Classic Snapback', colour: 'Black', style: 'snapback',
      reference_image_url: 'https://example.com/cap.jpg', view_images: {},
    },
    entryContext: null, view: 'canvas',
  })
})

describe('CustomiseStudio', () => {
  it('renders the canvas surface and the chat column side by side', () => {
    render(<CustomiseStudio />)
    expect(screen.getByTestId('surface')).toBeInTheDocument()
    expect(screen.getByTestId('chat-column')).toBeInTheDocument()
  })

  it('shows the shared header with the product breadcrumb', () => {
    render(<CustomiseStudio />)
    expect(screen.getByText('MAD HATS')).toBeInTheDocument()
    expect(screen.getByText(/Classic Snapback/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/CustomiseStudio.test.tsx`
Expected: FAIL — `Failed to resolve import '../components/CustomiseStudio'`.

- [ ] **Step 3: Create CustomiseStudio/index.tsx**

```tsx
import { useSessionStore } from '../../store/sessionStore'
import { DesignStudioSurface } from '../DesignStudio/Surface'
import { ChatColumn } from './ChatColumn'

/**
 * CustomiseStudio — the split-screen canvas experience.
 * LEFT: the full interactive canvas studio (DesignStudioSurface).
 * RIGHT: a live chat column (ChatColumn), dormant until "See it rendered"
 *        hydrates the chat store, then driving verify → deliver → refine
 *        in place (no full-screen ChatPanel handoff).
 */
export function CustomiseStudio() {
  const productRef = useSessionStore(s => s.productRef)

  return (
    <div className="h-screen bg-base flex flex-col">
      <header className="bg-surface border-b border-border px-6 py-3.5 flex items-center gap-3 flex-shrink-0">
        <span className="text-accent font-extrabold text-lg tracking-wide">MAD HATS</span>
        {productRef && (
          <span className="text-sm text-textMuted truncate">{productRef.name} › Design</span>
        )}
      </header>

      {/* Desktop: canvas (flex-1) left, chat (fixed) right. Mobile: stacked. */}
      <div className="flex-1 flex flex-col md:flex-row min-h-0">
        <div className="flex-1 flex min-h-0 min-w-0">
          <DesignStudioSurface />
        </div>
        <div className="border-t md:border-t-0 md:border-l border-border flex-shrink-0 w-full md:w-[380px] h-[45vh] md:h-auto flex flex-col min-h-0">
          <ChatColumn />
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/CustomiseStudio.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Wire App.tsx**

In `frontend/src/App.tsx`:
- Replace the import `import { DesignStudio } from './components/DesignStudio'` with `import { CustomiseStudio } from './components/CustomiseStudio'`.
- In the `sessionView === 'canvas'` branch, replace `return <DesignStudio />` with `return <CustomiseStudio />`.

Resulting branch:
```tsx
  if (sessionView === 'canvas') {
    return <CustomiseStudio />
  }
```

- [ ] **Step 6: Typecheck / build**

Run: `cd frontend && npm run build`
Expected: build succeeds — the `App.tsx` module error from Task 2 is now resolved.

- [ ] **Step 7: Full test suite**

Run: `cd frontend && npx vitest run`
Expected: previously-passing tests still pass (181 baseline + new ChatColumn/CustomiseStudio tests; the 2 pre-existing `adminQuotes` failures remain). If a Windows tinypool "Worker exited" flake appears, rerun the affected file focused.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/CustomiseStudio/index.tsx frontend/src/__tests__/CustomiseStudio.test.tsx frontend/src/App.tsx
git commit -m "feat(canvas): CustomiseStudio split-screen (canvas left, chat right) + wire App"
```

---

## Task 4: Manual browser verification

**Files:** none (verification only).

react-konva can't be unit-tested here, so the end-to-end canvas render path must be verified in the browser.

- [ ] **Step 1: Start the stack**

Ensure Supabase is up (`cd backend && npx supabase status`) and run `docker compose up` (backend :8000, frontend :5173). If env changed, `docker compose up -d --force-recreate backend`.

- [ ] **Step 2: Open a canvas session**

Navigate to a customise canvas entry, e.g. `http://localhost:5173/?product_id=<id>` (or `?mode=blank` → pick a hat → lands on the canvas). Confirm the **split screen**: canvas studio on the left (thumbnails / canvas / tool rail), chat column on the right showing the empty-state hint. No app-level console errors.

- [ ] **Step 3: Design + render**

Add a text element and/or upload an image; switch faces; (blank mode) pick a colour and confirm the tint shows. Click **"See it rendered"**.
Expected: the screen does **not** navigate away; the **right chat column** comes alive — generation panel runs, then (no email was collected up front) the chat asks for your email inline. Enter it in the chat input. The canvas stays visible on the left throughout.

- [ ] **Step 4: Verify → deliver → refine**

Click the emailed verification link (Mailpit at `http://localhost:54324`). Expected: the right panel advances to the collapsed verified/delivered message and offers a refine/tweak, all in place. The canvas remains on the left throughout.

- [ ] **Step 5: Regression — non-canvas flow untouched**

Open a non-canvas session path that still uses `ChatPanel` (the old customise/blank Q&A). Confirm it renders as before (preview left, chat right, full-screen). No commit needed — this task is verification only. If anything is broken, file the fix against the relevant earlier task.

---

## Self-Review Notes

- **Spec coverage:** §4.1 DesignStudioSurface → Task 2; §4.2 ChatColumn → Task 1; §4.3 ChatPanel untouched → Global Constraints + Task 1 (copy, not refactor); §4.4 App routing → Task 3; §5 layout (desktop/mobile/header) → Task 3 `index.tsx`; §7 testing → Tasks 1/3 unit + Task 4 manual (Konva constraint honored).
- **Kickoff subtlety:** `hydrate()` sets `kickoffDone: true`; canvas activates chat via finalize→hydrate, so `ChatColumn` deliberately omits the kickoff effect (Task 1 Step 3, tested in Step 1). This is the one behavioral divergence from `ChatPanel`.
- **Build is intentionally red between Task 2 and Task 3** (App still imports the deleted module) — called out in Task 2 Step 5 and resolved in Task 3 Step 6.
- **No new deps** — pure composition of existing components/stores, so the `node_modules`-volume gotcha does not apply.
