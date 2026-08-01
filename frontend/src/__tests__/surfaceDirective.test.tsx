import { render, screen, fireEvent, act } from '@testing-library/react'
import { expect, test, vi, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn().mockResolvedValue({ reply: 'ok', state: 'ask_another_logo', data: {} }),
  uploadLogo: vi.fn().mockResolvedValue({ asset_url: 'u', asset_hash: 'h' }),
  uploadCanvasLayouts: vi.fn().mockResolvedValue(undefined),
  finalizeCanvas: vi.fn().mockResolvedValue({ reply: 'ok', state: 'generating', data: {} }),
}))

import { DesignStudioSurface } from '../components/DesignStudio/Surface'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'
import { useCanvasStore } from '../store/canvasStore'
import { finalizeCanvas, sendChat } from '../lib/api'

// jsdom has no real <canvas> 2D backend (the `canvas` npm package isn't
// installed here), so `HTMLCanvasElement.getContext('2d')` returns null and a
// real Konva Stage can't mount at all. DesignStudioSurface mounts a real
// react-konva <CanvasStage>, so stub getContext the same way
// `lockedNode.test.tsx` does — a permissive no-op 2D context.
function stubCanvasContext(): CanvasRenderingContext2D {
  const noop = () => {}
  const store: Record<string, unknown> = {}
  return new Proxy(store, {
    get(target, prop: string) {
      if (prop in target) return target[prop]
      switch (prop) {
        case 'measureText': return () => ({ width: 0 })
        case 'createLinearGradient':
        case 'createRadialGradient': return () => ({ addColorStop: noop })
        case 'createPattern': return () => ({})
        case 'getImageData': return () => ({ data: new Uint8ClampedArray(4), width: 1, height: 1 })
        case 'canvas': return undefined
        default: return noop
      }
    },
    set(target, prop: string, value) {
      target[prop] = value
      return true
    },
  }) as unknown as CanvasRenderingContext2D
}

HTMLCanvasElement.prototype.getContext = ((() => stubCanvasContext()) as unknown) as typeof HTMLCanvasElement.prototype.getContext

// jsdom's toDataURL is "not implemented" (it logs and returns undefined), which
// makes doRender's flatten loop blow up before it ever reaches finalizeCanvas —
// so any test that puts an element on a face and then finalizes must stub it.
HTMLCanvasElement.prototype.toDataURL = ((() => 'data:image/png;base64,iVBORw0KGgo=') as unknown) as typeof HTMLCanvasElement.prototype.toDataURL

beforeEach(() => {
  useChatStore.getState().reset()
  useCanvasStore.getState().reset()
  useSessionStore.setState({ sessionId: 's1', productRef: null } as never)
})

test('directive shows the instruction callout and Done button', () => {
  useChatStore.setState({
    chatState: 'logo_adjust',
    canvasDirective: { allowedTools: ['upload'], targetFace: 'front', autoOpen: null, instructions: 'Drag to move it', showDone: true },
  } as never)
  render(<DesignStudioSurface />)
  expect(screen.getByText('Drag to move it')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /done/i })).toBeInTheDocument()
})

test('v2: SelectedToolbar mounts so a selected element is editable', () => {
  // Regression: the toolbar was gated on `unlocked` (chatState === 'canvas_design'),
  // which is always false in v2 — so directive copy telling the customer to change
  // font/size/colour "in the toolbar" pointed at a toolbar that never rendered.
  // targetFace null so the face-switch effect (which clears selectedId via
  // setActiveFace) doesn't fire — the active face is already 'front' by default.
  useChatStore.setState({
    chatState: 'text_adjust',
    canvasDirective: { allowedTools: ['text'], targetFace: null, autoOpen: null, instructions: 'Style your text', showDone: false },
  } as never)
  // Add a text element on the active face and select it — the toolbar no-ops
  // until something is selected, so a selection is what makes it appear.
  useCanvasStore.getState().addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id
  useCanvasStore.getState().select(id)
  render(<DesignStudioSurface />)
  // SelectedToolbar renders these text controls (stable aria-labels).
  expect(screen.getByLabelText('Text content')).toBeInTheDocument()
  expect(screen.getByLabelText('Font')).toBeInTheDocument()
})

test('clicking Done locks the just-placed element — when the DIRECTIVE leaves the editing step', async () => {
  // The lock is anchored to the directive, never to the Done button. postDone
  // used to call lockPlaced() itself; that locked the element BEFORE
  // chatStore.sendMessage read the canvas blob, which is what broke the
  // self-ticked background detection (see the blob test below). Clicking Done
  // must therefore leave the element alone; the lock lands when the reply moves
  // the flow off an editing step.
  useChatStore.setState({
    chatState: 'logo_adjust',
    canvasDirective: { allowedTools: ['upload'], targetFace: 'front', autoOpen: null, instructions: 'Drag to move it', showDone: true },
  } as never)
  useCanvasStore.getState().addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id
  expect(useCanvasStore.getState().faces.front[0].locked).toBeFalsy()

  const { rerender } = render(<DesignStudioSurface />)
  fireEvent.click(screen.getByRole('button', { name: /^done$/i }))
  // Let the mocked sendChat promise's async continuation settle inside an
  // act() so its state update doesn't land after the test body.
  await act(async () => { await new Promise(r => setTimeout(r, 0)) })

  // Still unlocked: ASK_LOGO_BG keeps the upload tool open on purpose, so the
  // logo stays selectable and the "Remove background" toggle stays reachable.
  act(() => {
    useChatStore.setState({
      chatState: 'ask_logo_bg',
      canvasDirective: { allowedTools: ['upload'], targetFace: 'front', autoOpen: null, instructions: 'Does it have a background?', showDone: false },
    } as never)
  })
  rerender(<DesignStudioSurface />)
  expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.locked).toBeFalsy()

  // The next step hands over no tools — that is what locks the placed element.
  act(() => {
    useChatStore.setState({
      chatState: 'ask_another_logo',
      canvasDirective: { allowedTools: [], targetFace: null, autoOpen: null, instructions: null, showDone: false },
    } as never)
  })
  rerender(<DesignStudioSurface />)
  expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.locked).toBe(true)
})

test('canvas Done sends the live canvas with the just-placed logo still UNLOCKED', async () => {
  // THE BUG this branch's headline feature died on: postDone() called
  // lockPlaced() synchronously before sendMessage, and chatStore.sendMessage
  // reads toCanvasDesign() synchronously too — so every element in the blob was
  // already locked:true. canvas_steps.observe_canvas skips locked images, so a
  // self-ticked "Remove background" was invisible on the canvas Done button
  // path, which is the path LOGO_ADJUST's own copy points at ("Select Done when
  // the placement looks right"). Two pre-existing bugs rode on the same line:
  // a locked element is unselectable (so the manual toggle was unreachable) and
  // _ops_logo_bg's canvas op targets the last UNLOCKED image, so it no-opped.
  vi.mocked(sendChat).mockClear()
  useChatStore.setState({
    chatState: 'logo_adjust',
    canvasDirective: { allowedTools: ['upload'], targetFace: 'front', autoOpen: null, instructions: 'Drag it', showDone: true },
  } as never)
  useCanvasStore.getState().addImage('logo.png', 1)
  const id = useCanvasStore.getState().faces.front[0].id
  useCanvasStore.getState().updateElement(id, { removeBg: true })

  render(<DesignStudioSurface />)
  fireEvent.click(screen.getByRole('button', { name: /^done$/i }))
  await act(async () => { await new Promise(r => setTimeout(r, 0)) })

  expect(sendChat).toHaveBeenCalledTimes(1)
  const design = vi.mocked(sendChat).mock.calls[0][2]
  expect(design).toBeTruthy()
  const logo = design!.faces.front.find(e => e.id === id)
  expect(logo).toBeTruthy()
  // The two facts observe_canvas needs: unlocked (so it is the pending logo)
  // and ticked (so it writes pending_logo["bg"] = "removed").
  expect(logo!.locked).toBeFalsy()
  expect(logo!.removeBg).toBe(true)
})

test('answering Done via the chat chip also locks the placed element', () => {
  // THE LOCK BUG: `LOGO_ADJUST` offers Done twice — the canvas button (which
  // runs postDone -> lockPlaced) AND a chat chip (options: ["Done"], which
  // calls sendMessage directly). Customers tap the chip, so lockPlaced never
  // ran: the chat said "Locked that in" while the logo stayed draggable.
  // Locking must follow the DIRECTIVE leaving a showDone step, not the button.
  useChatStore.setState({
    chatState: 'logo_adjust',
    canvasDirective: { allowedTools: ['upload'], targetFace: 'front', autoOpen: null, instructions: 'Drag it', showDone: true },
  } as never)
  useCanvasStore.getState().addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id

  const { rerender } = render(<DesignStudioSurface />)
  expect(useCanvasStore.getState().faces.front[0].locked).toBeFalsy()

  // The chip reply lands: the backend moves to ask_another_logo ("Locked that
  // in") — a step with no tools and no Done.
  act(() => {
    useChatStore.setState({
      chatState: 'ask_another_logo',
      canvasDirective: { allowedTools: [], targetFace: null, autoOpen: null, instructions: null, showDone: false },
    } as never)
  })
  rerender(<DesignStudioSurface />)

  expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.locked).toBe(true)
})

test('v2: the stage is read-only on a step that hands over no tools', () => {
  // Surface passed `locked={isV2 ? false : !unlocked}` — hardcoded false for
  // EVERY v2 turn — so the stage stayed interactive through the quantity/
  // email/purpose questions where the directive locks all tools.
  useChatStore.setState({
    chatState: 'ask_quantity',
    canvasDirective: { allowedTools: [], targetFace: null, autoOpen: null, instructions: null, showDone: false },
  } as never)
  useCanvasStore.getState().addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id
  useCanvasStore.getState().select(id)
  render(<DesignStudioSurface />)

  // No tools in play -> the element-editing toolbar must not be reachable.
  expect(screen.queryByLabelText('Text content')).not.toBeInTheDocument()
})

test('rework: unlock_all directive unlocks the canvas and Done sends chat, not finalizeCanvas', async () => {
  // Simulate a finished, locked design being reopened for rework (REWORK_CANVAS).
  useCanvasStore.getState().addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id
  useCanvasStore.getState().lockAll()
  expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.locked).toBe(true)

  const unlockSpy = vi.spyOn(useCanvasStore.getState(), 'unlockAll')

  useChatStore.setState({
    chatState: 'rework_canvas',
    canvasDirective: {
      allowedTools: ['upload', 'text', 'shape'],
      targetFace: null,
      autoOpen: null,
      instructions: 'Edit your design',
      showDone: true,
      unlockAll: true,
    },
  } as never)

  render(<DesignStudioSurface />)

  expect(unlockSpy).toHaveBeenCalled()
  expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.locked).toBe(false)

  // The ToolRail render/"Done designing" button must not be the active finalize
  // path during rework — only the per-step Done button submits.
  expect(screen.queryByRole('button', { name: /done designing|design saved/i })).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: /^done$/i }))
  await act(async () => { await new Promise(r => setTimeout(r, 0)) })

  // The live canvas now rides every turn (feeds the backend's Back checkpoint
  // snapshot) — REWORK_CANVAS is a v2-only state, so this is squarely in scope.
  expect(sendChat).toHaveBeenCalledWith('s1', 'done', expect.any(Object))
  expect(finalizeCanvas).not.toHaveBeenCalled()
})

test('a FAILED finalize re-opens the canvas so the rejected text can be edited', async () => {
  // C3: the cap-text profanity gate 422s with "please edit that text and try
  // again" — but FINALIZE_CANVAS declares no tool, so the directive gives
  // allowedTools: [] (stage read-only, Adjust panel unmounted) and the finalize
  // effect has already lockAll()'d every element. The customer was told to edit
  // text they physically could not touch.
  vi.mocked(finalizeCanvas).mockClear()
  vi.mocked(finalizeCanvas).mockRejectedValueOnce(
    new Error('We can\'t put "SHIT HAPPENS" on a product. Please edit that text and try again.'))

  useCanvasStore.getState().addText('SHIT HAPPENS')
  const id = useCanvasStore.getState().faces.front[0].id

  useChatStore.setState({
    chatState: 'finalize_canvas',
    canvasDirective: { allowedTools: [], targetFace: null, autoOpen: null, instructions: null, showDone: false },
    triggerFinalize: true,
  } as never)

  const { rerender } = render(<DesignStudioSurface />)
  // doRender's per-face export waits on two nested requestAnimationFrames per
  // decorated face (~32ms in jsdom), so a 0ms settle would leave the render
  // mid-flight — and its continuation would then land in the NEXT test.
  await act(async () => { await new Promise(r => setTimeout(r, 150)) })
  rerender(<DesignStudioSurface />)

  // The gate's message is surfaced...
  expect(screen.getByRole('alert')).toHaveTextContent(/edit that text/i)
  // ...and the canvas is editable again: every element unlocked, and the
  // Adjust panel reachable once the offending element is selected.
  expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.locked).toBe(false)
  expect(useChatStore.getState().triggerFinalize).toBe(false)

  act(() => { useCanvasStore.getState().select(id) })
  rerender(<DesignStudioSurface />)
  expect(screen.getByLabelText('Text content')).toBeInTheDocument()
})

test('a second trigger_finalize re-arms and fires again', async () => {
  // The refine confirm step fires trigger_finalize a SECOND time. The ref guard
  // was never re-armed, so the re-render was silently swallowed.
  vi.mocked(finalizeCanvas).mockClear()
  useChatStore.setState({
    chatState: 'generating',
    canvasDirective: null,
    triggerFinalize: true,
  } as never)
  const { rerender } = render(<DesignStudioSurface />)
  await act(async () => { await new Promise(r => setTimeout(r, 0)) })
  expect(finalizeCanvas).toHaveBeenCalledTimes(1)

  // Intervening turns: triggerFinalize drops back to false.
  act(() => { useChatStore.setState({ triggerFinalize: false } as never) })
  rerender(<DesignStudioSurface />)

  // The refine confirm turn fires it again.
  act(() => { useChatStore.setState({ triggerFinalize: true } as never) })
  rerender(<DesignStudioSurface />)
  await act(async () => { await new Promise(r => setTimeout(r, 0)) })

  expect(finalizeCanvas).toHaveBeenCalledTimes(2)
})
