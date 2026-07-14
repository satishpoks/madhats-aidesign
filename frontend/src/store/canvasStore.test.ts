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

  it('addImage inserts a wide image undistorted (aspect preserved)', () => {
    const s = useCanvasStore.getState()
    s.addImage('u.png', 2) // 2:1 wide
    const el = useCanvasStore.getState().faces.front[0]
    expect(el.type).toBe('image')
    expect(el.width).toBeGreaterThan(el.height)
    expect(el.width / el.height).toBeCloseTo(2, 5)
  })

  it('addImage inserts a tall image undistorted (aspect preserved)', () => {
    const s = useCanvasStore.getState()
    s.addImage('u.png', 0.5) // 1:2 tall
    const el = useCanvasStore.getState().faces.front[0]
    expect(el.height).toBeGreaterThan(el.width)
    expect(el.width / el.height).toBeCloseTo(0.5, 5)
  })

  it('addImage falls back to square for a bad aspect', () => {
    const s = useCanvasStore.getState()
    s.addImage('u.png', 0)
    const el = useCanvasStore.getState().faces.front[0]
    expect(el.width).toBe(el.height)
  })

  it('duplicate clones an element with a new id, offset + selected', () => {
    const s = useCanvasStore.getState()
    s.addText('HI')
    const src = useCanvasStore.getState().faces.front[0]
    s.duplicate(src.id)
    const after = useCanvasStore.getState().faces.front
    expect(after).toHaveLength(2)
    const copy = after[1]
    expect(copy.id).not.toBe(src.id)
    expect(copy.content).toBe('HI')
    expect(copy.x).toBeCloseTo(src.x + 0.04, 5)
    expect(useCanvasStore.getState().selectedId).toBe(copy.id)
  })

  it('updateElement sets a text curve', () => {
    const s = useCanvasStore.getState()
    s.addText('ARCH')
    const id = useCanvasStore.getState().faces.front[0].id
    s.updateElement(id, { curve: 60 })
    expect(useCanvasStore.getState().faces.front[0].curve).toBe(60)
  })

  it('addDrawing appends a drawing element with the current colour + width, selected', () => {
    const s = useCanvasStore.getState()
    s.setDrawColour('#ff0000'); s.setDrawWidth(0.02)
    s.addDrawing([0.1, 0.1, 0.2, 0.2])
    const el = useCanvasStore.getState().faces.front[0]
    expect(el.type).toBe('drawing')
    expect(el.points).toEqual([0.1, 0.1, 0.2, 0.2])
    expect(el.stroke).toBe('#ff0000')
    expect(el.strokeWidth).toBe(0.02)
    expect(useCanvasStore.getState().selectedId).toBe(el.id)
  })

  it('fromCanvasDesign rehydrates faces + colourway (inverse of toCanvasDesign)', () => {
    const s = useCanvasStore.getState()
    s.setColourway({ name: 'Navy', hex: '#1e3a8a' })
    s.setActiveFace('back')
    s.addText('RESUME')
    const saved = useCanvasStore.getState().toCanvasDesign()

    // Simulate a fresh page load (email "edit" link) then rehydrate.
    useCanvasStore.getState().reset()
    expect(useCanvasStore.getState().faces.back).toHaveLength(0)
    useCanvasStore.getState().fromCanvasDesign(saved)

    const st = useCanvasStore.getState()
    expect(st.colourway?.name).toBe('Navy')
    expect(st.faces.back[0].content).toBe('RESUME')
    expect(st.activeFace).toBe('front')
    expect(st.selectedId).toBeNull()
  })

  it('fromCanvasDesign tolerates a null/partial design', () => {
    const s = useCanvasStore.getState()
    s.addText('X')
    s.fromCanvasDesign(null)
    // Nulls out to an empty, valid design rather than throwing.
    const st = useCanvasStore.getState()
    expect(st.faces.front).toHaveLength(0)
    expect(st.colourway).toBeNull()
  })

  it('setDrawMode toggles draw mode and reset clears it', () => {
    const s = useCanvasStore.getState()
    s.setDrawMode(true)
    expect(useCanvasStore.getState().drawMode).toBe(true)
    useCanvasStore.getState().reset()
    expect(useCanvasStore.getState().drawMode).toBe(false)
  })
})
