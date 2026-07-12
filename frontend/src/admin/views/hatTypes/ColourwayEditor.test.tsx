import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ColourwayEditor } from './ColourwayEditor'

describe('ColourwayEditor', () => {
  it('adds an empty colour row', () => {
    const onChange = vi.fn()
    render(<ColourwayEditor value={[]} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /add colour/i }))
    expect(onChange).toHaveBeenCalledWith([{ name: '', hex: '#000000' }])
  })

  it('edits a colour name', () => {
    const onChange = vi.fn()
    render(<ColourwayEditor value={[{ name: '', hex: '#000000' }]} onChange={onChange} />)
    fireEvent.change(screen.getByLabelText('Colour 1 name'), { target: { value: 'Black' } })
    expect(onChange).toHaveBeenCalledWith([{ name: 'Black', hex: '#000000' }])
  })

  it('removes a colour row', () => {
    const onChange = vi.fn()
    render(
      <ColourwayEditor
        value={[{ name: 'Black', hex: '#000000' }, { name: 'Red', hex: '#ff0000' }]}
        onChange={onChange}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Remove colour 1' }))
    expect(onChange).toHaveBeenCalledWith([{ name: 'Red', hex: '#ff0000' }])
  })
})
