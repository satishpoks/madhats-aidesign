import { createRef } from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Watermark } from '../components/DesignStudio/Watermark'
import { CanvasStage } from '../components/DesignStudio/CanvasStage'
import { useChatStore } from '../store/chatStore'
import { useCanvasStore } from '../store/canvasStore'
import Konva from 'konva'
import { flattenFull, flattenStage } from '../lib/canvasFlatten'

// jsdom has no real <canvas> 2D backend (the `canvas` npm package isn't
// installed here), so `HTMLCanvasElement.getContext('2d')` returns null and a
// real Konva Stage can't mount at all. Stub getContext with a permissive
// no-op 2D context, same as `lockedNode.test.tsx`/`surfaceDirective.test.tsx` —
// local to this file, since it's the only test here mounting a real Konva
// Stage. Also stub toDataURL, which jsdom logs as "not implemented" and
// returns undefined for, so flattenStage/flattenFull have something to return.
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
HTMLCanvasElement.prototype.toDataURL = ((() => 'data:image/png;base64,iVBORw0KGgo=') as unknown) as typeof HTMLCanvasElement.prototype.toDataURL

describe('Watermark overlay', () => {
  it('renders the configured text and is inert', () => {
    render(<Watermark text="MADHATS PREVIEW" />)
    const el = screen.getByTestId('canvas-watermark')
    // The text is baked into an SVG background-image data URI, not text
    // content — assert it's actually in there, not just that *some* image is.
    expect(el.style.backgroundImage).toContain(encodeURIComponent('MADHATS PREVIEW'))
    // aria-hidden: it is decoration over content the customer can already read.
    expect(el).toHaveAttribute('aria-hidden', 'true')
    // pointer-events-none: it sits over the Konva stage; without this it would
    // swallow every drag, click and transform on the canvas beneath it.
    expect(el.className).toContain('pointer-events-none')
  })

  it('escapes XML-special characters so a store-configured "&" cannot produce malformed SVG', () => {
    render(<Watermark text="Smith & Co" />)
    const el = screen.getByTestId('canvas-watermark')
    expect(el.style.backgroundImage).toContain(encodeURIComponent('Smith &amp; Co'))
  })

  it('chatStore parses the backend watermark flag', () => {
    useChatStore.setState({ watermark: false })
    useChatStore.getState().applyResponse('hi', 'review_design', { watermark: true })
    expect(useChatStore.getState().watermark).toBe(true)
  })

  it('defaults to watermarked on a v2 turn that carries a directive but no flag', () => {
    // `state_machine_v2.public_data_for` is the only producer of the flag and it
    // always sends `canvas` alongside — so "directive present, flag absent" is
    // the shape to be lenient about, and the design is finished by then.
    useChatStore.setState({ watermark: false })
    useChatStore.getState().applyResponse('hi', 'generating', {
      canvas: { allowed_tools: [], target_face: null, auto_open: null, instructions: null },
    })
    expect(useChatStore.getState().watermark).toBe(true)
  })

  it('does NOT watermark a payload with no canvas directive at all', () => {
    // REPLACES an earlier assertion that ANY absent flag meant watermarked.
    // That default was only ever reasoned about for v2; it also caught every
    // producer that knows nothing about watermarking:
    //   - v1's `_public_data` (CANVAS_ORCHESTRATOR_V2=false is the code
    //     default), which watermarked a v1 canvas session from the greeting
    //     onward — including `canvas_design`, i.e. across a live design the
    //     customer is still dragging logos around on;
    //   - `sessions._public_data`, so ANY resume — a v2 canvas session
    //     resumed mid-design came back watermarked over its live design.
    // Both are exactly what the watermark design says must stay clean.
    useChatStore.setState({ watermark: true })
    useChatStore.getState().applyResponse('hi', 'canvas_design', { options: ['a'] })
    expect(useChatStore.getState().watermark).toBe(false)
  })

  it('still honours an explicit flag when one is sent', () => {
    // The gate is on the DEFAULT only. An explicit value from any producer
    // wins, in both directions — REWORK_CANVAS's `false` (reworking IS
    // editing) and a watermarked step's `true`.
    useChatStore.setState({ watermark: false })
    useChatStore.getState().applyResponse('hi', 'request_quote', { watermark: true })
    expect(useChatStore.getState().watermark).toBe(true)

    useChatStore.getState().applyResponse('hi', 'rework_canvas', {
      watermark: false,
      canvas: { allowed_tools: ['upload'], target_face: null, auto_open: null, instructions: null },
    })
    expect(useChatStore.getState().watermark).toBe(false)
  })

  it('flattenStage/flattenFull tolerate a DOM sibling next to the stage (smoke check, not the safety proof)', () => {
    // NOT the safety proof — this only shows the flatten functions don't throw
    // when an unrelated DOM node with the same testid sits beside the stage's
    // container. stage.find() can never match a plain DOM element regardless of
    // whether Watermark is a DOM sibling, a Konva node, or doesn't exist at all,
    // so this cannot detect a regression where the watermark moves INTO the
    // Konva tree. The real safety proof is the differential test below.
    const container = document.createElement('div')
    document.body.appendChild(container)
    const stage = new Konva.Stage({ container, width: 480, height: 480 })
    stage.add(new Konva.Layer())

    const overlay = document.createElement('div')
    overlay.setAttribute('data-testid', 'canvas-watermark')
    container.appendChild(overlay)

    expect(() => flattenStage(stage)).not.toThrow()
    expect(() => flattenFull(stage)).not.toThrow()
    stage.destroy()
    container.remove()
  })

  it('mounting the real <Watermark> beside the real <CanvasStage> adds nothing to the Konva scene graph', () => {
    // The actual safety proof. It renders the REAL components in the exact
    // structure Surface.tsx uses (the watermark handed to <CanvasStage> as its
    // `overlay`, which renders it as a plain-DOM sibling of the Konva stage
    // inside CanvasStage's own `relative` box), then inventories the real
    // Konva scene graph (every Stage/Layer/Group/Shape descendant, via the same
    // Konva `.find()` API flattenStage/flattenFull walk) with and without the
    // watermark mounted.
    //
    // Falsifiable by construction: if a future reimplementation moved the
    // watermark INTO the Konva tree — e.g. a Konva.Text layer, or a node
    // inserted via a portal into the Stage — the "with watermark" inventory
    // would contain an extra node absent from the baseline, and the equality
    // assertion below would fail. It does not depend on canvas pixel output
    // (jsdom's toDataURL is stubbed to a constant, which is exactly why a
    // pixel/byte comparison would be vacuous here) — it reads the real Konva
    // node objects Konva itself tracks, independent of that stub.
    useCanvasStore.getState().reset()

    const refA = createRef<Konva.Stage>()
    const withoutWatermark = render(
      <CanvasStage stageRef={refA} locked={false} />,
    )
    const stageA = refA.current!
    const namesWithout = stageA.find(() => true).map(n => n.getClassName()).sort()
    withoutWatermark.unmount()
    stageA.destroy()

    const refB = createRef<Konva.Stage>()
    const withWatermark = render(
      <CanvasStage stageRef={refB} locked={false} overlay={<Watermark text="MADHATS PREVIEW" />} />,
    )
    const stageB = refB.current!
    const namesWith = stageB.find(() => true).map(n => n.getClassName()).sort()
    withWatermark.unmount()
    stageB.destroy()

    // Sanity: the stage actually has nodes to compare (a Layer, at minimum) —
    // otherwise an empty-vs-empty comparison would itself be vacuous.
    expect(namesWithout.length).toBeGreaterThan(0)
    expect(namesWith).toEqual(namesWithout)
  })
})
