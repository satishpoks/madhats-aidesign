import { beforeEach, expect, test } from 'vitest'
import { useCanvasStore } from '../store/canvasStore'
import { parseCanvasOps, applyCanvasOps } from '../lib/canvasOps'

beforeEach(() => useCanvasStore.getState().reset())

test('parseCanvasOps returns [] when the key is absent or malformed', () => {
  expect(parseCanvasOps({})).toEqual([])
  expect(parseCanvasOps({ canvas_ops: 'nope' })).toEqual([])
})

test('parseCanvasOps drops ops with an unknown target kind or bad face', () => {
  const ops = parseCanvasOps({
    canvas_ops: [
      { target: { kind: 'wat', face: 'front' }, patch: { x: 0.1 } },
      { target: { kind: 'element', id: 'a', face: 'nose' }, patch: { x: 0.1 } },
      { target: { kind: 'pending_logo', face: 'front' }, patch: { removeBg: true } },
    ],
  })
  expect(ops).toHaveLength(1)
  expect(ops[0].target.kind).toBe('pending_logo')
})

test('applyCanvasOps patches a pending logo', () => {
  const s = useCanvasStore.getState()
  s.addImage('logo.png')
  applyCanvasOps([{ target: { kind: 'pending_logo', face: 'front' }, patch: { removeBg: true } }])
  expect(useCanvasStore.getState().faces.front[0].removeBg).toBe(true)
})

test('applyCanvasOps patches and removes elements by id', () => {
  const s = useCanvasStore.getState()
  s.addText('a'); s.addText('b')
  const [a, b] = useCanvasStore.getState().faces.front.map(e => e.id)
  applyCanvasOps([
    { target: { kind: 'element', id: a, face: 'front' }, patch: { x: 0.75 } },
    { target: { kind: 'element', id: b, face: 'front' }, remove: true },
  ])
  const { faces } = useCanvasStore.getState()
  expect(faces.front).toHaveLength(1)
  expect(faces.front[0].x).toBe(0.75)
})
