import { beforeEach, expect, test } from 'vitest'
import { useCanvasStore } from '../store/canvasStore'

beforeEach(() => useCanvasStore.getState().reset())

test('lockAll marks every element locked', () => {
  const s = useCanvasStore.getState()
  s.addText('a')
  s.setActiveFace('back'); s.addText('b')
  s.lockAll()
  const { faces } = useCanvasStore.getState()
  expect(faces.front[0].locked).toBe(true)
  expect(faces.back[0].locked).toBe(true)
})

test('lockPlaced locks every unlocked element and leaves already-locked ones', () => {
  const s = useCanvasStore.getState()
  s.addText('a')
  const firstId = useCanvasStore.getState().faces.front[0].id
  s.lockAll() // simulate a prior step's lock
  s.setActiveFace('front')
  s.addText('b') // the just-placed element, still unlocked
  s.lockPlaced()
  const { faces } = useCanvasStore.getState()
  expect(faces.front.find(e => e.id === firstId)?.locked).toBe(true)
  expect(faces.front[1].locked).toBe(true)
})

test('lockPlaced clears the current selection', () => {
  const s = useCanvasStore.getState()
  s.addText('a')
  const id = useCanvasStore.getState().faces.front[0].id
  s.select(id)
  expect(useCanvasStore.getState().selectedId).toBe(id)
  s.lockPlaced()
  expect(useCanvasStore.getState().selectedId).toBeNull()
})
