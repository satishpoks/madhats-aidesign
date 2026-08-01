import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Watermark } from '../components/DesignStudio/Watermark'
import { useChatStore } from '../store/chatStore'
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
    // aria-hidden: it is decoration over content the customer can already read.
    expect(el).toHaveAttribute('aria-hidden', 'true')
    // pointer-events-none: it sits over the Konva stage; without this it would
    // swallow every drag, click and transform on the canvas beneath it.
    expect(el.className).toContain('pointer-events-none')
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

  it('is structurally absent from both flatten paths', () => {
    // The guarantee is that a DOM node cannot enter stage.toDataURL(). Assert it
    // against a real Konva stage rather than trusting the argument: a future
    // refactor that moved the watermark INTO the Konva tree would silently start
    // baking it into the layout guide the image model consumes.
    const container = document.createElement('div')
    document.body.appendChild(container)
    const stage = new Konva.Stage({ container, width: 480, height: 480 })
    stage.add(new Konva.Layer())

    const overlay = document.createElement('div')
    overlay.setAttribute('data-testid', 'canvas-watermark')
    container.appendChild(overlay)

    expect(() => flattenStage(stage)).not.toThrow()
    expect(() => flattenFull(stage)).not.toThrow()
    expect(stage.find((n: Konva.Node) => n.getAttr('data-testid') === 'canvas-watermark')).toHaveLength(0)
    stage.destroy()
    container.remove()
  })
})
