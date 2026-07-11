import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { Modal } from './index'

describe('Modal', () => {
  it('renders nothing when closed', () => {
    render(
      <Modal open={false} title="Hi">
        <p>body</p>
      </Modal>,
    )
    expect(screen.queryByText('body')).not.toBeInTheDocument()
  })

  it('renders title and children when open', () => {
    render(
      <Modal open title="Upload your logo">
        <p>body</p>
      </Modal>,
    )
    expect(screen.getByRole('dialog', { name: /upload your logo/i })).toBeInTheDocument()
    expect(screen.getByText('body')).toBeInTheDocument()
  })

  it('calls onClose from the ✕ button and Escape when dismissible', () => {
    const onClose = vi.fn()
    render(
      <Modal open title="Hi" onClose={onClose}>
        <p>body</p>
      </Modal>,
    )
    fireEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalledTimes(1)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('shows no close control when onClose is omitted (non-dismissible)', () => {
    render(
      <Modal open title="Hi">
        <p>body</p>
      </Modal>,
    )
    expect(screen.queryByRole('button', { name: /close/i })).not.toBeInTheDocument()
  })
})
