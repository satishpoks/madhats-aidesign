import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ChipListEditor } from './ChipListEditor'

describe('ChipListEditor', () => {
  it('adds a chip on Enter', () => {
    const onChange = vi.fn()
    render(<ChipListEditor label="Zones" value={[]} onChange={onChange} />)
    const input = screen.getByLabelText('Zones')
    fireEvent.change(input, { target: { value: 'Front panel' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith(['Front panel'])
  })

  it('removes a chip via its × button', () => {
    const onChange = vi.fn()
    render(<ChipListEditor label="Zones" value={['Front panel', 'Back']} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Remove Front panel' }))
    expect(onChange).toHaveBeenCalledWith(['Back'])
  })

  it('adds a suggestion on click and skips duplicates', () => {
    const onChange = vi.fn()
    render(
      <ChipListEditor label="Zones" value={['Back']} onChange={onChange} suggestions={['Back', 'Front panel']} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Add Front panel' }))
    expect(onChange).toHaveBeenCalledWith(['Back', 'Front panel'])
  })
})
