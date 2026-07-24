import { beforeEach, expect, test } from 'vitest'
import { useCanvasStore } from '../store/canvasStore'
import type { CanvasDesign } from '../store/canvasStore'

beforeEach(() => useCanvasStore.getState().reset())

test('unlockAll clears locked on every element across all faces', () => {
  const s = useCanvasStore.getState()
  s.addText('a')
  s.setActiveFace('back'); s.addText('b')
  s.lockAll()
  expect(useCanvasStore.getState().faces.front[0].locked).toBe(true)
  expect(useCanvasStore.getState().faces.back[0].locked).toBe(true)

  useCanvasStore.getState().unlockAll()
  const { faces } = useCanvasStore.getState()
  expect(faces.front[0].locked).toBe(false)
  expect(faces.back[0].locked).toBe(false)
})

test('unlockAll clears the current selection', () => {
  const s = useCanvasStore.getState()
  s.addText('a')
  const id = useCanvasStore.getState().faces.front[0].id
  s.select(id)
  expect(useCanvasStore.getState().selectedId).toBe(id)
  s.unlockAll()
  expect(useCanvasStore.getState().selectedId).toBeNull()
})

test('fromCanvasDesign strips a persisted locked flag so resumed elements are editable', () => {
  const design: CanvasDesign = {
    colourway: null,
    faces: {
      front: [{
        id: 'x1', type: 'text', x: 0.5, y: 0.4, width: 0.3, height: 0.12,
        rotation: 0, zIndex: 0, content: 'hi', locked: true,
      }],
      back: [], left: [], right: [],
    },
  }
  useCanvasStore.getState().fromCanvasDesign(design)
  const el = useCanvasStore.getState().faces.front[0]
  expect(el.content).toBe('hi')
  expect(el.locked).toBeFalsy()
})
