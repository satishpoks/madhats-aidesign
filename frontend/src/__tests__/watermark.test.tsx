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

  it('defaults to watermarked when the backend sends no flag', () => {
    // A shared-tail state (generating / verify / refine / quote) has no registry
    // step, so no flag is sent — and the design IS finished in all of them.
    useChatStore.setState({ watermark: false })
    useChatStore.getState().applyResponse('hi', 'generating', {})
    expect(useChatStore.getState().watermark).toBe(true)
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
    // structure Surface.tsx uses (`<div className="relative">` wrapping
    // <CanvasStage> with <Watermark> as a sibling), then inventories the real
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
      <div className="relative">
        <CanvasStage stageRef={refA} locked={false} />
      </div>,
    )
    const stageA = refA.current!
    const namesWithout = stageA.find(() => true).map(n => n.getClassName()).sort()
    withoutWatermark.unmount()
    stageA.destroy()

    const refB = createRef<Konva.Stage>()
    const withWatermark = render(
      <div className="relative">
        <CanvasStage stageRef={refB} locked={false} />
        <Watermark text="MADHATS PREVIEW" />
      </div>,
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
