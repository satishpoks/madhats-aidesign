import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SelectedToolbar } from '../components/DesignStudio/SelectedToolbar'
import { useCanvasStore, TEXT_PLACEHOLDER } from '../store/canvasStore'

function reset() {
  useCanvasStore.setState({
    faces: { front: [], back: [], left: [], right: [] },
    activeFace: 'front',
    selectedId: null,
  })
}

describe('text element content field', () => {
  beforeEach(reset)

  it('renders a visible label, not just an aria-label', () => {
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
    render(<SelectedToolbar />)
    expect(screen.getByText('Your text')).toBeInTheDocument()
  })

  it('is full width rather than the old w-28', () => {
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
    render(<SelectedToolbar />)
    const input = screen.getByLabelText('Text content')
    expect(input.className).toContain('w-full')
    expect(input.className).not.toContain('w-28')
  })

  it('focuses and selects a freshly added element so typing replaces the placeholder', () => {
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
    render(<SelectedToolbar />)
    const input = screen.getByLabelText('Text content') as HTMLInputElement
    expect(document.activeElement).toBe(input)
    expect(input.selectionStart).toBe(0)
    expect(input.selectionEnd).toBe(TEXT_PLACEHOLDER.length)
  })

  it('does NOT steal focus for an element that has already been edited', () => {
    useCanvasStore.getState().addText('MADHATS')
    render(<SelectedToolbar />)
    const input = screen.getByLabelText('Text content')
    expect(document.activeElement).not.toBe(input)
  })

  it('still writes content through the store', async () => {
    useCanvasStore.getState().addText('MADHATS')
    render(<SelectedToolbar />)
    const input = screen.getByLabelText('Text content')
    await userEvent.clear(input)
    await userEvent.type(input, 'CREW')
    expect(useCanvasStore.getState().faces.front[0].content).toBe('CREW')
  })
})
