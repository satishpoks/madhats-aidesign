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

test('unlockAll clears locked', () => {
  const s = useCanvasStore.getState()
  s.addText('a'); s.lockAll(); s.unlockAll()
  expect(useCanvasStore.getState().faces.front[0].locked).toBe(false)
})
