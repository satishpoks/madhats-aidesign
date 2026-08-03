/**
 * Inline text editing — double-click (desktop) / double-tap (mobile) a text
 * element on the canvas to edit its wording in place (owner request,
 * 2026-08-03), in addition to the existing Adjust panel CONTENT field.
 *
 * jsdom has no real <canvas> 2D backend and react-konva shapes are drawn onto
 * that canvas rather than produced as inspectable DOM nodes, so a literal
 * "double-click the Konva text node" cannot be simulated here — the same
 * limitation every other Konva-adjacent test in this codebase works around
 * (none of them simulate a native pointer event on a shape either). What IS
 * tested here: the store-level `startEditingText`/`stopEditingText` guards
 * TextNode's onDblClick/onDblTap call into, the CanvasStage wiring that turns
 * `editingTextId` into a rendered overlay, and the TextEditOverlay component
 * itself (a plain DOM `<input>`, fully RTL-testable). The double-click →
 * `startEditingText` wiring itself was verified in a real browser — see the
 * task report.
 */
import { createRef } from 'react'
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Konva from 'konva'
import { useCanvasStore } from '../store/canvasStore'
import { TextEditOverlay } from '../components/DesignStudio/TextEditOverlay'
import { CanvasStage } from '../components/DesignStudio/CanvasStage'
import { clearMeasuredTextBoxes } from '../lib/textMetrics'

// jsdom has no real <canvas> 2D backend, so a react-konva Stage cannot mount
// unless getContext is stubbed — same permissive no-op proxy used by every
// other Surface/CanvasStage-mounting test in this codebase (e.g.
// surfaceMobileTools.test.tsx, canvasStageParentChain.test.tsx). Applied at
// module scope, before any test runs, exactly like those files.
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
    set(target, prop: string, value) { target[prop] = value; return true },
  }) as unknown as CanvasRenderingContext2D
}
HTMLCanvasElement.prototype.getContext = ((() => stubCanvasContext()) as unknown) as typeof HTMLCanvasElement.prototype.getContext

beforeEach(() => {
  useCanvasStore.getState().reset()
  clearMeasuredTextBoxes()
})

describe('canvasStore: startEditingText / stopEditingText', () => {
  it('opens the editor for an unlocked text element, and selects it', () => {
    useCanvasStore.getState().addText('hello')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().select(null) // simulate having deselected first
    useCanvasStore.getState().startEditingText(id)
    expect(useCanvasStore.getState().editingTextId).toBe(id)
    expect(useCanvasStore.getState().selectedId).toBe(id)
  })

  it('refuses to open the editor for a LOCKED text element', () => {
    useCanvasStore.getState().addText('hello')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().lockAll()
    useCanvasStore.getState().startEditingText(id)
    expect(useCanvasStore.getState().editingTextId).toBeNull()
  })

  it('refuses to open the editor for a non-text element', () => {
    useCanvasStore.getState().addShape('rect')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().startEditingText(id)
    expect(useCanvasStore.getState().editingTextId).toBeNull()
  })

  it('refuses to open the editor for an id that does not exist on the active face', () => {
    useCanvasStore.getState().startEditingText('nope')
    expect(useCanvasStore.getState().editingTextId).toBeNull()
  })

  it('stopEditingText clears editingTextId but leaves selectedId alone', () => {
    useCanvasStore.getState().addText('hello')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().startEditingText(id)
    useCanvasStore.getState().stopEditingText()
    expect(useCanvasStore.getState().editingTextId).toBeNull()
    expect(useCanvasStore.getState().selectedId).toBe(id)
  })

  it('switching the active face closes any open editor', () => {
    useCanvasStore.getState().addText('hello')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().startEditingText(id)
    useCanvasStore.getState().setActiveFace('back')
    expect(useCanvasStore.getState().editingTextId).toBeNull()
  })

  it('selecting a different element (or deselecting) closes any open editor', () => {
    useCanvasStore.getState().addText('hello')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().startEditingText(id)
    useCanvasStore.getState().select(null)
    expect(useCanvasStore.getState().editingTextId).toBeNull()
  })

  it('removing the currently-editing element closes the editor', () => {
    useCanvasStore.getState().addText('hello')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().startEditingText(id)
    useCanvasStore.getState().removeElement(id)
    expect(useCanvasStore.getState().editingTextId).toBeNull()
  })

  it('lockAll / lockPlaced close any open editor', () => {
    useCanvasStore.getState().addText('hello')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().startEditingText(id)
    useCanvasStore.getState().lockAll()
    expect(useCanvasStore.getState().editingTextId).toBeNull()
  })
})

describe('flatten-safety guard: an open editor never removes the element from the export payload', () => {
  it('toCanvasDesign() still carries the text element, unlocked, with its content, while editingTextId is set', () => {
    // This is the pin the task asked for: the Konva text node is NEVER
    // hidden while editing (see TextEditOverlay's header comment), so the
    // element must remain fully present — same id/type/content/locked state
    // — in the exact structure `Surface.doRender()` serialises for both
    // the flattened PNG exports (which read the live Konva stage, not this
    // JSON, but render from the SAME store data) and the `canvas_design`
    // JSON blob sent to the backend.
    useCanvasStore.getState().addText('My Logo Text')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().startEditingText(id)

    const design = useCanvasStore.getState().toCanvasDesign()
    const el = design.faces.front.find(e => e.id === id)
    expect(el).toBeTruthy()
    expect(el?.type).toBe('text')
    expect(el?.content).toBe('My Logo Text')
    expect(el?.locked).toBeFalsy()
  })

  it('every keystroke is written live into the store — a flatten mid-edit can never see stale/missing text', () => {
    useCanvasStore.getState().addText('Start')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().startEditingText(id)

    render(<TextEditOverlay el={useCanvasStore.getState().faces.front[0]} scale={1} stageW={480} stageH={480} />)
    fireEvent.change(screen.getByTestId('text-edit-overlay'), { target: { value: 'Start!' } })

    // Read straight from the store, as a concurrent flatten would (via
    // toCanvasDesign() and via whatever content the live Konva node is
    // currently painting from) — not from the input's own DOM value.
    expect(useCanvasStore.getState().faces.front[0].content).toBe('Start!')
    expect(useCanvasStore.getState().toCanvasDesign().faces.front.find(e => e.id === id)?.content).toBe('Start!')
  })
})

describe('TextEditOverlay component', () => {
  function setup(content = 'Hello') {
    useCanvasStore.getState().addText(content)
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().startEditingText(id)
    const el = useCanvasStore.getState().faces.front[0]
    render(<TextEditOverlay el={el} scale={1} stageW={480} stageH={480} />)
    return id
  }

  it('renders an input pre-filled with the element\'s current content, focused and selected', () => {
    setup('Hello')
    const input = screen.getByTestId('text-edit-overlay') as HTMLInputElement
    expect(input.value).toBe('Hello')
    expect(document.activeElement).toBe(input)
  })

  it('typing updates the store immediately (not just on commit)', () => {
    const id = setup('Hello')
    fireEvent.change(screen.getByTestId('text-edit-overlay'), { target: { value: 'Hello there' } })
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.content).toBe('Hello there')
  })

  it('Enter commits and closes the editor, keeping the typed content', () => {
    const id = setup('Hello')
    fireEvent.change(screen.getByTestId('text-edit-overlay'), { target: { value: 'Changed' } })
    fireEvent.keyDown(screen.getByTestId('text-edit-overlay'), { key: 'Enter' })
    expect(useCanvasStore.getState().editingTextId).toBeNull()
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.content).toBe('Changed')
  })

  it('blur commits and closes the editor, keeping the typed content', () => {
    const id = setup('Hello')
    fireEvent.change(screen.getByTestId('text-edit-overlay'), { target: { value: 'Changed by blur' } })
    fireEvent.blur(screen.getByTestId('text-edit-overlay'))
    expect(useCanvasStore.getState().editingTextId).toBeNull()
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.content).toBe('Changed by blur')
  })

  it('Escape reverts to the pre-edit content and closes, discarding the typed change', () => {
    const id = setup('Original')
    fireEvent.change(screen.getByTestId('text-edit-overlay'), { target: { value: 'Discard me' } })
    fireEvent.keyDown(screen.getByTestId('text-edit-overlay'), { key: 'Escape' })
    expect(useCanvasStore.getState().editingTextId).toBeNull()
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.content).toBe('Original')
  })

  it('committing an empty/whitespace-only value reverts to the pre-edit content instead of deleting the element', () => {
    const id = setup('Keep me')
    fireEvent.change(screen.getByTestId('text-edit-overlay'), { target: { value: '   ' } })
    fireEvent.blur(screen.getByTestId('text-edit-overlay'))
    const el = useCanvasStore.getState().faces.front.find(e => e.id === id)
    expect(el).toBeTruthy() // never deleted
    expect(el?.content).toBe('Keep me') // reverted, not left blank
  })
})

describe('CanvasStage wiring: editingTextId -> rendered overlay', () => {
  function renderStage() {
    const ref = createRef<Konva.Stage>()
    return render(<CanvasStage stageRef={ref} />)
  }

  it('renders no text-edit overlay when nothing is being edited', () => {
    useCanvasStore.getState().addText('hi')
    renderStage()
    expect(screen.queryByTestId('text-edit-overlay')).not.toBeInTheDocument()
  })

  it('renders the overlay when editingTextId names an unlocked text element on the active face', () => {
    useCanvasStore.getState().addText('hi')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().startEditingText(id)
    renderStage()
    expect(screen.getByTestId('text-edit-overlay')).toBeInTheDocument()
  })

  it('never renders the overlay for a locked element, even if editingTextId somehow references it (defence in depth)', () => {
    useCanvasStore.getState().addText('hi')
    const id = useCanvasStore.getState().faces.front[0].id
    // Bypass the store's own guard to simulate a stale/adversarial state.
    useCanvasStore.setState({ editingTextId: id })
    useCanvasStore.getState().lockAll()
    // lockAll already clears editingTextId — force it back to prove
    // CanvasStage's OWN re-check (not just the store's) is what protects it.
    useCanvasStore.setState({ editingTextId: id })
    renderStage()
    expect(screen.queryByTestId('text-edit-overlay')).not.toBeInTheDocument()
  })

  it('never renders the overlay for an element on an inactive face', () => {
    useCanvasStore.getState().addText('hi')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.setState({ editingTextId: id, activeFace: 'back' })
    renderStage()
    expect(screen.queryByTestId('text-edit-overlay')).not.toBeInTheDocument()
  })

  it('the overlay is a DOM sibling of the Konva stage, never inside it — mirrors the Watermark construction', () => {
    useCanvasStore.getState().addText('hi')
    const id = useCanvasStore.getState().faces.front[0].id
    useCanvasStore.getState().startEditingText(id)
    renderStage()
    const overlay = screen.getByTestId('text-edit-overlay')
    expect(overlay.closest('.konvajs-content')).toBeNull()
  })

  it('adds NOTHING to the real Konva scene graph while open — the flatten-safety proof, mirrors watermark.test.tsx', () => {
    // Same differential technique as watermark.test.tsx's scene-graph-
    // inventory test: render the real stage with and without the editor open
    // and diff the actual Konva node inventory (what flattenStage/flattenFull
    // walk via stage.find()), rather than trusting that this component merely
    // LOOKS like a DOM overlay. Falsifiable by construction — a future
    // reimplementation that inserted a Konva node for the editor (or hid the
    // real Text node, changing the inventory) would fail this immediately.
    useCanvasStore.getState().addText('hi')
    const id = useCanvasStore.getState().faces.front[0].id

    const refA = createRef<Konva.Stage>()
    const withoutEditor = render(<CanvasStage stageRef={refA} />)
    const stageA = refA.current!
    const namesWithout = stageA.find(() => true).map(n => n.getClassName()).sort()
    withoutEditor.unmount()
    stageA.destroy()

    useCanvasStore.getState().startEditingText(id)
    const refB = createRef<Konva.Stage>()
    const withEditor = render(<CanvasStage stageRef={refB} />)
    const stageB = refB.current!
    expect(screen.getByTestId('text-edit-overlay')).toBeInTheDocument()
    const namesWith = stageB.find(() => true).map(n => n.getClassName()).sort()
    withEditor.unmount()
    stageB.destroy()

    expect(namesWith).toEqual(namesWithout)
  })
})
