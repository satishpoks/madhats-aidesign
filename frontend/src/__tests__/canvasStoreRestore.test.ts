import { describe, it, expect, beforeEach } from 'vitest'
import { useCanvasStore } from '../store/canvasStore'

const design = {
  colourway: 'navy',
  faces: {
    front: [{ id: 'a', type: 'image', x: 0.5, y: 0.5, locked: true } as never,
            { id: 'b', type: 'image', x: 0.2, y: 0.2, locked: false } as never],
    back: [], left: [], right: [],
  },
}

describe('restoreSnapshot', () => {
  beforeEach(() => useCanvasStore.getState().reset())

  it('preserves lock state, unlike fromCanvasDesign', () => {
    useCanvasStore.getState().restoreSnapshot(design as never)
    const front = useCanvasStore.getState().faces.front
    expect(front.map(e => e.locked)).toEqual([true, false])
  })

  it('fromCanvasDesign still unlocks everything (rework path unchanged)', () => {
    useCanvasStore.getState().fromCanvasDesign(design as never)
    expect(useCanvasStore.getState().faces.front.every(e => !e.locked)).toBe(true)
  })

  it('restores the colourway and clears the selection', () => {
    useCanvasStore.getState().restoreSnapshot(design as never)
    expect(useCanvasStore.getState().colourway).toBe('navy')
    expect(useCanvasStore.getState().selectedId).toBeNull()
  })

  it('tolerates a partial blob with missing faces', () => {
    useCanvasStore.getState().restoreSnapshot({ faces: { front: [] } } as never)
    expect(useCanvasStore.getState().faces.right).toEqual([])
  })

  it('is a no-op-safe call for null', () => {
    expect(() => useCanvasStore.getState().restoreSnapshot(null)).not.toThrow()
  })
})
