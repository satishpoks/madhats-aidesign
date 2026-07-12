import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { BasicsFields } from './BasicsFields'

describe('BasicsFields', () => {
  it('renders current values and reports edits', () => {
    const onChange = vi.fn()
    render(
      <BasicsFields value={{ name: 'Trucker', style: 'trucker', description: '' }} onChange={onChange} />,
    )
    expect(screen.getByLabelText('Name')).toHaveValue('Trucker')
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Dad Cap' } })
    expect(onChange).toHaveBeenCalledWith({ name: 'Dad Cap', style: 'trucker', description: '' })
  })
})
