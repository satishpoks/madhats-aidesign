import { describe, it, expect, beforeEach } from 'vitest'
import { useCanvasStore } from '../store/canvasStore'

beforeEach(() => {
  useCanvasStore.getState().reset()
})

describe('canvasStore draw tool', () => {
  it('selects the new drawing after committing a stroke', () => {
    useCanvasStore.getState().setDrawMode(true)
    useCanvasStore.getState().addDrawing([0.1, 0.1, 0.2, 0.2])
    const s = useCanvasStore.getState()
    const drawing = s.faces.front.find(e => e.type === 'drawing')
    expect(drawing).toBeTruthy()
    expect(s.selectedId).toBe(drawing!.id)
  })

  it('exits draw mode after committing a stroke so the drawing is selectable', () => {
    // While drawMode is on, CanvasStage disables layer listening, so an element
    // can only be clicked/moved once draw mode is off.
    useCanvasStore.getState().setDrawMode(true)
    useCanvasStore.getState().addDrawing([0.1, 0.1, 0.2, 0.2])
    expect(useCanvasStore.getState().drawMode).toBe(false)
  })
})

describe('canvasStore image upload', () => {
  it('stores assetPath on uploaded images and round-trips it', () => {
    const s = useCanvasStore.getState()
    s.reset()
    s.addImage('http://x/sign/a.png?t=1', 1, 'canvas_front_A.png')
    const el = useCanvasStore.getState().faces.front[0]
    expect(el.assetPath).toBe('canvas_front_A.png')
    expect(useCanvasStore.getState().toCanvasDesign().faces.front[0].assetPath).toBe('canvas_front_A.png')
  })
})
