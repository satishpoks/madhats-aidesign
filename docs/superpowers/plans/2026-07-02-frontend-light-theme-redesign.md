# Frontend Light-Theme Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-skin the active React chat studio from dark to a light theme matching the MadHats Figma design language, polish layout/placement, and replace the click-to-toggle mic with a hold-SPACEBAR push-to-talk voice control.

**Architecture:** The frontend already consumes semantic Tailwind color tokens everywhere, so the dark→light flip is primarily a token redefinition in `tailwind.config.js` (plus fixing the few hardcoded-color spots), after which each component is polished for placement. Voice gains a `usePushToTalk` hook layered over the existing `useSpeechRecognition`, adding global spacebar keydown/keyup handling with strict focus/repeat guards.

**Tech Stack:** React 18, Vite, TypeScript, Tailwind CSS 3, Zustand, Vitest + @testing-library/react, Web Speech API.

## Global Constraints

- No backend changes; the server-rendered quote page (`GET /quote/{token}`) is out of scope.
- No new npm dependencies. Web Speech API stays the only STT source; degrade gracefully where unsupported (Firefox, jsdom).
- Keep the existing conversation/generation data flow untouched — presentation + input UX only.
- Generated design is delivered by email only: the viewer keeps showing blank product angles, never the preview. Do not change that copy.
- Accent colors stay exactly `accent = #FF5C00`, `accentHover = #E64F00`.
- Light palette (exact values): `base #F7F8FA`, `surface #FFFFFF`, `surfaceAlt #EEF0F4`, `border #E5E7EB`, `textPrimary #1A1D29`, `textSub #4B5563`, `textMuted #8A90A0`, new `ink #1E2130`.
- Run frontend tests with `npx vitest run` from `frontend/` (bare `npm test` is watch mode and hangs).
- Commit after each task.

---

### Task 1: Redefine Tailwind tokens to light + add `ink`

**Files:**
- Modify: `frontend/tailwind.config.js:6-16` (the `colors` block)
- Modify: `frontend/src/index.css:14-25` (the `.shimmer` utility gradient)

**Interfaces:**
- Consumes: nothing.
- Produces: light values for existing tokens `base`, `surface`, `surfaceAlt`, `border`, `textPrimary`, `textSub`, `textMuted`; a new token `ink` (`#1E2130`). `accent`/`accentHover` unchanged. These class names (`bg-base`, `text-ink`, etc.) are relied on by every later task.

- [ ] **Step 1: Edit the color tokens**

In `frontend/tailwind.config.js`, replace the `colors` object with:

```js
      colors: {
        base: '#F7F8FA',
        surface: '#FFFFFF',
        surfaceAlt: '#EEF0F4',
        border: '#E5E7EB',
        ink: '#1E2130',
        accent: '#FF5C00',
        accentHover: '#E64F00',
        textPrimary: '#1A1D29',
        textMuted: '#8A90A0',
        textSub: '#4B5563',
      },
```

- [ ] **Step 2: Recolor the shimmer gradient for light**

In `frontend/src/index.css`, replace the `.shimmer` background gradient dark hex stops with light grays:

```css
  .shimmer {
    background: linear-gradient(
      90deg,
      #EEF0F4 25%,
      #F7F8FA 50%,
      #EEF0F4 75%
    );
    background-size: 800px 100%;
    animation: shimmer 1.6s infinite linear;
  }
```

- [ ] **Step 3: Verify the build compiles**

Run: `cd frontend && npx vitest run`
Expected: test run completes (some existing color-class assertions may still pass since class names are unchanged); no build/TS errors. Note any failures for later tasks.

- [ ] **Step 4: Commit**

```bash
git add frontend/tailwind.config.js frontend/src/index.css
git commit -m "feat(frontend): light theme color tokens + ink header token"
```

---

### Task 2: `usePushToTalk` hook (hold-spacebar to talk)

**Files:**
- Create: `frontend/src/hooks/usePushToTalk.ts`
- Test: `frontend/src/__tests__/usePushToTalk.test.tsx`

**Interfaces:**
- Consumes: `useSpeechRecognition(onResult)` from `frontend/src/hooks/useSpeechRecognition.ts`, which returns `{ supported: boolean, listening: boolean, start: () => void, stop: () => void }`.
- Produces: `usePushToTalk(onResult: (text: string) => void, opts?: { enabled?: boolean }): { supported: boolean; listening: boolean; start: () => void; stop: () => void }`. When `supported` and `enabled !== false`, it registers global `keydown`/`keyup` listeners so holding Space starts listening and releasing stops it, with focus/repeat guards. `start`/`stop`/`listening`/`supported` are passed through from `useSpeechRecognition` for the mic button.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/usePushToTalk.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'

// Mock the underlying speech hook so we can assert start/stop calls.
const start = vi.fn()
const stop = vi.fn()
let supported = true
vi.mock('../hooks/useSpeechRecognition', () => ({
  useSpeechRecognition: () => ({ supported, listening: false, start, stop }),
}))

import { usePushToTalk } from '../hooks/usePushToTalk'

function pressSpace(target: EventTarget = document.body, extra: Partial<KeyboardEventInit> = {}) {
  fireEvent.keyDown(target, { key: ' ', code: 'Space', ...extra })
}
function releaseSpace(target: EventTarget = document.body) {
  fireEvent.keyUp(target, { key: ' ', code: 'Space' })
}

describe('usePushToTalk', () => {
  beforeEach(() => {
    start.mockReset()
    stop.mockReset()
    supported = true
    document.body.innerHTML = ''
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
  })

  it('starts on space keydown and stops on keyup when nothing is focused', () => {
    renderHook(() => usePushToTalk(vi.fn()))
    pressSpace()
    expect(start).toHaveBeenCalledTimes(1)
    releaseSpace()
    expect(stop).toHaveBeenCalledTimes(1)
  })

  it('ignores auto-repeat keydown (starts once)', () => {
    renderHook(() => usePushToTalk(vi.fn()))
    pressSpace(document.body)
    pressSpace(document.body, { repeat: true })
    expect(start).toHaveBeenCalledTimes(1)
  })

  it('does not start when an input is focused', () => {
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    renderHook(() => usePushToTalk(vi.fn()))
    pressSpace(input)
    expect(start).not.toHaveBeenCalled()
  })

  it('does not start when a button is focused', () => {
    const btn = document.createElement('button')
    document.body.appendChild(btn)
    btn.focus()
    renderHook(() => usePushToTalk(vi.fn()))
    pressSpace(btn)
    expect(start).not.toHaveBeenCalled()
  })

  it('is a no-op when speech is unsupported', () => {
    supported = false
    renderHook(() => usePushToTalk(vi.fn()))
    pressSpace()
    releaseSpace()
    expect(start).not.toHaveBeenCalled()
    expect(stop).not.toHaveBeenCalled()
  })

  it('does not register listeners when enabled is false', () => {
    renderHook(() => usePushToTalk(vi.fn(), { enabled: false }))
    pressSpace()
    expect(start).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/usePushToTalk.test.tsx`
Expected: FAIL — cannot resolve `../hooks/usePushToTalk`.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/hooks/usePushToTalk.ts`:

```ts
import { useEffect, useRef } from 'react'
import { useSpeechRecognition } from './useSpeechRecognition'

interface PushToTalkOptions {
  /** When false, the global spacebar listeners are not registered. Default true. */
  enabled?: boolean
}

interface UsePushToTalk {
  supported: boolean
  listening: boolean
  start: () => void
  stop: () => void
}

/** True when the currently focused element should swallow the spacebar itself. */
function focusIsInteractive(): boolean {
  const el = document.activeElement as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'BUTTON') return true
  if (el.isContentEditable) return true
  return false
}

/**
 * Walkie-talkie voice: hold SPACEBAR to talk, release to send.
 * Wraps useSpeechRecognition and adds global key handling with guards so a
 * held key starts recognition exactly once and typing spaces never triggers it.
 * Falls back cleanly (no listeners) where the Web Speech API is unavailable.
 */
export function usePushToTalk(
  onResult: (text: string) => void,
  opts: PushToTalkOptions = {},
): UsePushToTalk {
  const { supported, listening, start, stop } = useSpeechRecognition(onResult)
  const enabled = opts.enabled !== false

  // Track whether OUR spacebar hold is the active source, so keyup only stops
  // recognition we started.
  const holdingRef = useRef(false)

  useEffect(() => {
    if (!supported || !enabled) return

    function onKeyDown(e: KeyboardEvent) {
      if (e.code !== 'Space' && e.key !== ' ') return
      if (e.repeat) return
      if (focusIsInteractive()) return
      e.preventDefault()
      if (holdingRef.current) return
      holdingRef.current = true
      start()
    }

    function onKeyUp(e: KeyboardEvent) {
      if (e.code !== 'Space' && e.key !== ' ') return
      if (!holdingRef.current) return
      holdingRef.current = false
      e.preventDefault()
      stop()
    }

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
    }
  }, [supported, enabled, start, stop])

  return { supported, listening, start, stop }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/usePushToTalk.test.tsx`
Expected: PASS — all 6 tests green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/usePushToTalk.ts frontend/src/__tests__/usePushToTalk.test.tsx
git commit -m "feat(frontend): usePushToTalk hold-spacebar voice hook"
```

---

### Task 3: Wire push-to-talk + light voice UI into ChatPanel composer

**Files:**
- Modify: `frontend/src/components/ChatPanel/index.tsx:401-404` (replace `useSpeechRecognition` usage) and `:551-584` (composer form + mic button)
- Test: `frontend/src/__tests__/ChatPanel.test.tsx` (add a case; keep existing green)

**Interfaces:**
- Consumes: `usePushToTalk(onResult, { enabled })` from Task 2.
- Produces: composer renders a mic button (press-and-hold via pointer events + click fallback) and a persistent "Hold space to talk" hint when `speech.supported`. Push-to-talk is disabled (`enabled: false`) while `sending` so a held space mid-send doesn't fire.

- [ ] **Step 1: Add a failing test for the hint**

In `frontend/src/__tests__/ChatPanel.test.tsx`, add (adapt imports/setup to the file's existing pattern — it already renders `<ChatPanel />` with a mocked session):

```tsx
it('shows the hold-space-to-talk hint when speech is supported', async () => {
  // jsdom lacks SpeechRecognition; define a stub so `supported` is true.
  ;(window as unknown as Record<string, unknown>).SpeechRecognition = class {
    lang = ''; interimResults = false; continuous = false
    onresult = null; onend = null; onerror = null
    start() {} stop() {} abort() {}
  }
  renderChatPanel() // use the file's existing render helper
  expect(await screen.findByText(/hold space to talk/i)).toBeInTheDocument()
  delete (window as unknown as Record<string, unknown>).SpeechRecognition
})
```

If the test file has no shared `renderChatPanel` helper, inline the same render the other tests in that file use.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/ChatPanel.test.tsx`
Expected: FAIL — hint text not found.

- [ ] **Step 3: Swap the hook**

In `frontend/src/components/ChatPanel/index.tsx`, replace the import and usage. Change the import line:

```tsx
import { usePushToTalk } from '../../hooks/usePushToTalk'
```

Replace the `useSpeechRecognition(...)` block (~lines 401-404) with:

```tsx
  // Voice input — hold SPACEBAR (or press-and-hold the mic) to talk; the
  // transcript is sent straight through as a chat turn. Disabled while a
  // send is in flight so a held space can't fire mid-request.
  const speech = usePushToTalk(
    (transcript: string) => {
      if (sessionId && !sending) void sendMessage(sessionId, transcript)
    },
    { enabled: !sending },
  )
```

- [ ] **Step 4: Update the composer markup (mic button + hint)**

Replace the composer `<form>...</form>` block (~lines 552-584) with:

```tsx
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            placeholder={speech.listening ? 'Listening…' : 'Type or speak a message…'}
            disabled={sending}
            className="flex-1 bg-surface border border-border rounded-xl px-4 py-3 text-sm text-textPrimary placeholder:text-textMuted focus:outline-none focus:border-accent disabled:opacity-50 transition-colors"
          />
          {speech.supported && (
            <button
              type="button"
              onPointerDown={e => { e.preventDefault(); if (!sending) speech.start() }}
              onPointerUp={() => speech.stop()}
              onPointerLeave={() => { if (speech.listening) speech.stop() }}
              disabled={sending}
              aria-label={speech.listening ? 'Listening — release to send' : 'Hold to speak'}
              title={speech.listening ? 'Release to send' : 'Hold to speak'}
              className={`px-4 rounded-xl text-sm font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                speech.listening
                  ? 'bg-red-500 text-white animate-pulse'
                  : 'bg-surface border border-border text-textPrimary hover:border-accent hover:text-accent'
              }`}
            >
              {speech.listening ? '● Listening' : '🎤 Speak'}
            </button>
          )}
          <button
            type="submit"
            disabled={sending || !inputText.trim()}
            className="bg-accent hover:bg-accentHover text-white px-5 py-3 rounded-xl text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send
          </button>
        </form>
        {speech.supported && (
          <p className="text-xs text-textMuted text-center -mt-1">
            {speech.listening ? 'Listening… release space to send' : 'Hold space to talk'}
          </p>
        )}
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd frontend && npx vitest run src/__tests__/ChatPanel.test.tsx`
Expected: PASS — new hint test green and all pre-existing ChatPanel tests still green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChatPanel/index.tsx frontend/src/__tests__/ChatPanel.test.tsx
git commit -m "feat(frontend): spacebar push-to-talk + press-hold mic in composer"
```

---

### Task 4: Light-theme ChatPanel chrome (header, bubbles, chips, error banner)

**Files:**
- Modify: `frontend/src/components/ChatPanel/index.tsx` — header (`:415-419`), error banner (`:436-450`), message bubbles (`:461-467`), TypingIndicator (`:13-34`), and GenerationPanel spinner text colors (`:294-321`).

**Interfaces:**
- Consumes: light tokens from Task 1 (`ink`, `surface`, `border`, etc.).
- Produces: no new exported interfaces; visual only.

- [ ] **Step 1: Dark-navy header bar**

Replace the `<header>` (~lines 415-419) with:

```tsx
      <header className="bg-ink px-6 py-4 flex items-center gap-3 flex-shrink-0">
        <span className="text-accent font-bold text-xl tracking-tight">MadHats</span>
        <span className="text-white/30 text-xl">|</span>
        <span className="text-white/80 text-sm font-medium">AI Design Studio</span>
        <span className="ml-auto text-xs text-white/70 border border-white/20 px-3 py-1 rounded-full">
          Beta Preview
        </span>
      </header>
```

- [ ] **Step 2: Light error banner**

Replace the error banner block (~lines 436-450) so the alert uses light-red classes:

```tsx
      {chatError && (
        <div
          role="alert"
          className="mx-6 mt-4 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 flex-shrink-0"
        >
          <p className="flex-1 text-sm text-red-700">{chatError}</p>
          <button
            aria-label="Dismiss error"
            onClick={dismissError}
            className="flex-shrink-0 text-xs text-red-500 hover:text-red-700 transition-colors"
          >
            Dismiss
          </button>
        </div>
      )}
```

- [ ] **Step 3: Message bubble shadow for depth on light**

In the message list, update the assistant bubble branch (~lines 461-467) to add a subtle shadow so white bubbles separate from the light canvas:

```tsx
            <div
              className={`max-w-[80%] md:max-w-md px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-accent text-white rounded-br-sm'
                  : 'bg-surface text-textPrimary border border-border rounded-bl-sm shadow-sm'
              }`}
            >
              {msg.text}
            </div>
```

- [ ] **Step 4: TypingIndicator + GenerationPanel error-text colors**

In `TypingIndicator` (~lines 13-34) the dots use `bg-textMuted` — leave as-is (reads fine on light). In the error banner within `PinAnnotator`/`LogoUploader`, change `text-red-400` to `text-red-600` for contrast on light. Search the file for `text-red-400` and replace each occurrence with `text-red-600`.

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run src/__tests__/ChatPanel.test.tsx`
Expected: PASS. If a test asserts the old `bg-red-950/40` or header border classes, update the assertion to the new class.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChatPanel/index.tsx
git commit -m "feat(frontend): light-theme ChatPanel header, bubbles, banners"
```

---

### Task 5: Light polish for ProductViewer + ApiProductPicker

**Files:**
- Modify: `frontend/src/components/ProductViewer/index.tsx` (main image card `:67-73`, thumbnails `:112-124`)
- Modify: `frontend/src/components/ApiProductPicker/index.tsx` (header `:73-82`, product card hover `:154-158`)
- Test: `frontend/src/__tests__/ApiProductPicker.test.tsx` (keep green)

**Interfaces:**
- Consumes: light tokens from Task 1.
- Produces: visual only.

- [ ] **Step 1: ProductViewer main image card shadow**

In `frontend/src/components/ProductViewer/index.tsx`, update the main image container (~lines 67) to add `shadow-sm` so the white card lifts off the light canvas:

```tsx
      <div className="flex-1 min-h-0 flex items-center justify-center bg-surface border border-border rounded-2xl overflow-hidden shadow-sm">
```

- [ ] **Step 2: ApiProductPicker dark-navy header**

In `frontend/src/components/ApiProductPicker/index.tsx`, replace the `<header>` (~lines 73-82) with:

```tsx
      <header className="bg-ink px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-accent font-bold text-xl tracking-tight">MadHats</span>
          <span className="text-white/30 text-xl">|</span>
          <span className="text-white/80 text-sm font-medium">AI Design Studio</span>
        </div>
        <span className="text-xs text-white/70 border border-white/20 px-3 py-1 rounded-full">
          Beta Preview
        </span>
      </header>
```

- [ ] **Step 3: Product card hover ring uses accent token**

In the product card button (~lines 154-158), the `hover:shadow-[0_0_0_1px_#FF5C00]` already uses the accent hex — keep it, but add `shadow-sm` for a resting lift on light:

```tsx
                <button
                  key={product.id}
                  onClick={() => void handleSelect(product)}
                  className="bg-surface border border-border rounded-2xl p-4 text-left cursor-pointer group hover:border-accent transition-all duration-200 shadow-sm hover:shadow-[0_0_0_1px_#FF5C00] animate-fadeIn"
                >
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/__tests__/ApiProductPicker.test.tsx`
Expected: PASS. Update any assertion pinning the old header border/color classes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ProductViewer/index.tsx frontend/src/components/ApiProductPicker/index.tsx
git commit -m "feat(frontend): light polish for ProductViewer and ApiProductPicker"
```

---

### Task 6: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: ALL tests pass (including the new `usePushToTalk.test.tsx` and the new ChatPanel hint test). If any test fails only because it pinned a dark color class, update that single assertion to the corresponding light class and re-run.

- [ ] **Step 2: Type/build check**

Run: `cd frontend && npm run build`
Expected: Vite + tsc build succeeds with no errors.

- [ ] **Step 3: Manual smoke (optional but recommended)**

Run: `cd frontend && npm run dev`, open the dev URL. Confirm: light theme throughout, dark-navy header, chat bubbles/chips readable, mic button press-and-hold works, holding Space (with focus outside the input) starts/stops listening, and the "Hold space to talk" hint shows.

- [ ] **Step 4: Commit any assertion fixups**

```bash
git add -A
git commit -m "test(frontend): align color-class assertions with light theme"
```

(Skip if nothing changed.)

---

## Self-Review Notes

- **Spec coverage:** §3 palette → Task 1. §4 header → Tasks 4/5; ChatPanel bubbles/chips/banner → Task 4; ProductViewer/ApiProductPicker → Task 5; retired screens explicitly out of scope (inherit tokens). §5 voice → Tasks 2 (hook) + 3 (wiring/UI). §6 testing → Tasks 2, 3, 6. §7 files → all covered.
- **Placeholders:** none — all code steps include full code.
- **Type consistency:** `usePushToTalk(onResult, { enabled })` signature defined in Task 2 is consumed verbatim in Task 3; passthrough shape `{ supported, listening, start, stop }` matches `useSpeechRecognition`.
- **Note:** option chips (`options`/`options2`) and the "Continue" pill in ChatPanel already use token classes (`bg-surface`, `border-border`, `hover:border-accent`) and flip automatically with Task 1 — no dedicated step needed.
