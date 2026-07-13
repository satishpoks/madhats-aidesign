import { describe, it, expect, beforeEach } from 'vitest'
import { useCanvasStore } from './canvasStore'

beforeEach(() => useCanvasStore.getState().reset())

describe('canvasStore', () => {
  it('adds a text element to the active face', () => {
    const s = useCanvasStore.getState()
    s.setActiveFace('front')
    s.addText('SURF')
    const el = useCanvasStore.getState().faces.front[0]
    expect(el.type).toBe('text')
    expect(el.content).toBe('SURF')
  })

  it('updateElement patches only the target', () => {
    const s = useCanvasStore.getState()
    s.addText('A'); s.addText('B')
    const id = useCanvasStore.getState().faces.front[0].id
    s.updateElement(id, { colour: '#ff0000' })
    expect(useCanvasStore.getState().faces.front[0].colour).toBe('#ff0000')
    expect(useCanvasStore.getState().faces.front[1].colour).toBeUndefined()
  })

  it('removeElement drops it and clears selection', () => {
    const s = useCanvasStore.getState()
    s.addText('A')
    const id = useCanvasStore.getState().faces.front[0].id
    s.select(id); s.removeElement(id)
    expect(useCanvasStore.getState().faces.front).toHaveLength(0)
    expect(useCanvasStore.getState().selectedId).toBeNull()
  })

  it('toCanvasDesign serialises faces + colourway', () => {
    const s = useCanvasStore.getState()
    s.setColourway({ name: 'Navy', hex: '#1e3a8a' })
    s.addText('HI')
    const d = s.toCanvasDesign()
    expect(d.colourway?.name).toBe('Navy')
    expect(d.faces.front[0].content).toBe('HI')
    expect(Object.keys(d.faces)).toEqual(['front', 'back', 'left', 'right'])
  })
})
