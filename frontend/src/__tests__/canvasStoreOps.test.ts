import { beforeEach, expect, test } from 'vitest'
import { useCanvasStore } from '../store/canvasStore'
import { applyCanvasOps } from '../lib/canvasOps'

beforeEach(() => useCanvasStore.getState().reset())

test('patchElement patches the named face, not the active one', () => {
  const s = useCanvasStore.getState()
  s.setActiveFace('back'); s.addText('b')
  const backId = useCanvasStore.getState().faces.back[0].id
  s.setActiveFace('front')          // customer is looking elsewhere
  s.patchElement('back', backId, { x: 0.9 })
  expect(useCanvasStore.getState().faces.back[0].x).toBe(0.9)
})

test('patchElement patches a locked element', () => {
  // Ops arrive after lockAll() has frozen the canvas at finalize; the lock
  // stops the CUSTOMER dragging, not the bot editing.
  const s = useCanvasStore.getState()
  s.addText('a')
  const id = useCanvasStore.getState().faces.front[0].id
  s.lockAll()
  s.patchElement('front', id, { x: 0.1 })
  expect(useCanvasStore.getState().faces.front[0].x).toBe(0.1)
})

test('removeElementOn removes from the named face', () => {
  const s = useCanvasStore.getState()
  s.setActiveFace('left'); s.addText('x')
  const id = useCanvasStore.getState().faces.left[0].id
  s.setActiveFace('front')
  s.removeElementOn('left', id)
  expect(useCanvasStore.getState().faces.left).toHaveLength(0)
})

test('patchPendingLogo targets the last unlocked image on the face', () => {
  const s = useCanvasStore.getState()
  s.addImage('old.png')                       // an earlier logo…
  s.lockPlaced()                              // …already locked in by a prior step
  s.addImage('new.png')                       // the one just placed
  s.patchPendingLogo('front', { removeBg: true })
  const { faces } = useCanvasStore.getState()
  expect(faces.front[0].removeBg).toBeFalsy()
  expect(faces.front[1].removeBg).toBe(true)
})

test('patchPendingLogo ignores text and shapes', () => {
  const s = useCanvasStore.getState()
  s.addImage('logo.png')
  s.addText('later text')                     // unlocked, but not an image
  s.patchPendingLogo('front', { removeBg: true })
  const { faces } = useCanvasStore.getState()
  expect(faces.front[0].removeBg).toBe(true)
})

test('patchPendingLogo is a no-op when the face has no unlocked image', () => {
  const s = useCanvasStore.getState()
  s.addImage('logo.png')
  s.lockAll()
  expect(() => s.patchPendingLogo('front', { removeBg: true })).not.toThrow()
  expect(useCanvasStore.getState().faces.front[0].removeBg).toBeFalsy()
})

test('removePending drops the last unlocked element of any type on the face', () => {
  const s = useCanvasStore.getState()
  s.setActiveFace('back'); s.addText('t')       // a decor, not an image
  s.removePending('back')
  expect(useCanvasStore.getState().faces.back).toHaveLength(0)
})

test('removePending keeps locked elements and older placed ones', () => {
  const s = useCanvasStore.getState()
  s.addImage('kept.png'); s.lockPlaced()        // locked, must survive
  s.addImage('current.png')                     // the one just placed
  s.removePending('front')
  const { faces } = useCanvasStore.getState()
  expect(faces.front).toHaveLength(1)
  expect(faces.front[0].assetUrl).toBe('kept.png')
})

test('removePending is a no-op when nothing is unlocked', () => {
  const s = useCanvasStore.getState()
  s.addImage('logo.png'); s.lockAll()
  expect(() => s.removePending('front')).not.toThrow()
  expect(useCanvasStore.getState().faces.front).toHaveLength(1)
})

test('applyCanvasOps remove on a pending_logo target calls removePending', () => {
  const s = useCanvasStore.getState()
  s.setActiveFace('left'); s.addText('x')
  applyCanvasOps([{ target: { kind: 'pending_logo', face: 'left' }, remove: true }])
  expect(useCanvasStore.getState().faces.left).toHaveLength(0)
})
