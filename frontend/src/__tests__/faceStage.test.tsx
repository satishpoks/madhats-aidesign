import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { FaceStage } from '../components/DesignStudio/FaceStage'
import { useCanvasStore } from '../store/canvasStore'

// jsdom has no real <canvas> 2D backend (the `canvas` npm package isn't
// installed here), so `HTMLCanvasElement.getContext('2d')` returns null and a
// real Konva Stage can't mount at all. Same permissive no-op 2D context stub
// used elsewhere in this codebase's Konva-adjacent tests (e.g.
// watermark.test.tsx, designStudioCenterPivotSmoke.test.tsx).
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

describe('FaceStage', () => {
  it('renders at the requested size', () => {
    useCanvasStore.setState({ activeFace: 'front' })
    const { container } = render(<FaceStage face="front" size={320} fontsTick={0} />)
    const canvas = container.querySelector('canvas')
    expect(canvas).not.toBeNull()
    expect(canvas!.getAttribute('width')).toBe('320')
  })

  it('renders at thumbnail size too, from the same component', () => {
    const { container } = render(<FaceStage face="front" size={64} fontsTick={0} />)
    expect(container.querySelector('canvas')!.getAttribute('width')).toBe('64')
  })
})
