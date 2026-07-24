import { beforeEach, describe, expect, test } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SelectedToolbar } from '../components/DesignStudio/SelectedToolbar'
import { useCanvasStore } from '../store/canvasStore'

beforeEach(() => useCanvasStore.getState().reset())

function selectedText() {
  const s = useCanvasStore.getState()
  s.addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id
  s.select(id)
  return id
}

describe('SelectedToolbar transform controls', () => {
  test('+45° / −45° rotate and normalise into [0,360)', () => {
    const id = selectedText()
    render(<SelectedToolbar />)
    fireEvent.click(screen.getByRole('button', { name: 'Rotate right 45 degrees' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.rotation).toBe(45)
    // 45 - 45 - 45 wraps: click −45 twice → 45 → 0 → 315
    fireEvent.click(screen.getByRole('button', { name: 'Rotate left 45 degrees' }))
    fireEvent.click(screen.getByRole('button', { name: 'Rotate left 45 degrees' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.rotation).toBe(315)
  })

  test('custom degree input sets rotation and Reset zeroes it', () => {
    const id = selectedText()
    render(<SelectedToolbar />)
    fireEvent.change(screen.getByLabelText('Rotation degrees'), { target: { value: '123' } })
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.rotation).toBe(123)
    fireEvent.click(screen.getByRole('button', { name: 'Reset rotation' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.rotation).toBe(0)
  })

  test('move nudges shift x/y by a fixed delta, clamped to [0,1]', () => {
    const id = selectedText() // default x=0.5, y=0.4
    render(<SelectedToolbar />)
    fireEvent.click(screen.getByRole('button', { name: 'Nudge right' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.x).toBeCloseTo(0.52, 5)
    fireEvent.click(screen.getByRole('button', { name: 'Nudge up' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.y).toBeCloseTo(0.38, 5)
  })

  test('size on TEXT scales fontSize (not width/height), min 8', () => {
    const id = selectedText() // default fontSize 36
    render(<SelectedToolbar />)
    fireEvent.click(screen.getByRole('button', { name: 'Increase size' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.fontSize).toBe(40) // round(36*1.1)
    fireEvent.click(screen.getByRole('button', { name: 'Decrease size' }))
    fireEvent.click(screen.getByRole('button', { name: 'Decrease size' }))
    // 40 -> round(40/1.1)=36 -> round(36/1.1)=33
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.fontSize).toBe(33)
  })

  test('size on an IMAGE scales width and height together', () => {
    const s = useCanvasStore.getState()
    s.addImage('http://x/a.png', 1) // square → width=height=0.4
    const id = useCanvasStore.getState().faces.front[0].id
    s.select(id)
    render(<SelectedToolbar />)
    const before = useCanvasStore.getState().faces.front[0]
    fireEvent.click(screen.getByRole('button', { name: 'Increase size' }))
    const after = useCanvasStore.getState().faces.front.find(e => e.id === id)!
    expect(after.width).toBeCloseTo(before.width * 1.1, 5)
    expect(after.height).toBeCloseTo(before.height * 1.1, 5)
  })

  test('drawings offer rotate + move but NO size buttons', () => {
    const s = useCanvasStore.getState()
    s.addDrawing([0.1, 0.1, 0.2, 0.2])
    const id = useCanvasStore.getState().faces.front[0].id
    s.select(id)
    render(<SelectedToolbar />)
    expect(screen.getByRole('button', { name: 'Rotate right 45 degrees' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Nudge right' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Increase size' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Decrease size' })).not.toBeInTheDocument()
  })
})
