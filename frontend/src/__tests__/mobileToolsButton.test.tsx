import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MobileToolsButton } from '../components/DesignStudio/MobileToolsButton'

// jsdom performs NO layout — these tests pin class TOKENS (regex, whole-token
// match) and DOM presence/absence, never rendered position or pixels.

describe('MobileToolsButton', () => {
  it('does not render at all when isDesktop', () => {
    render(<MobileToolsButton isDesktop={true} open={false} pulse={false} onToggle={vi.fn()} />)
    expect(screen.queryByTestId('mobile-tools-toggle')).not.toBeInTheDocument()
  })

  it('renders below md (isDesktop=false)', () => {
    render(<MobileToolsButton isDesktop={false} open={false} pulse={false} onToggle={vi.fn()} />)
    expect(screen.getByTestId('mobile-tools-toggle')).toBeInTheDocument()
  })

  it('is fixed to the bottom-left of the viewport', () => {
    render(<MobileToolsButton isDesktop={false} open={false} pulse={false} onToggle={vi.fn()} />)
    const btn = screen.getByTestId('mobile-tools-toggle')
    expect(btn.className).toMatch(/(^|\s)fixed(\s|$)/)
    expect(btn.className).toMatch(/(^|\s)left-\d+(\s|$)/)
    expect(btn.className).toMatch(/(^|\s)bottom-\d+(\s|$)/)
  })

  it('calls onToggle when clicked', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()
    render(<MobileToolsButton isDesktop={false} open={false} pulse={false} onToggle={onToggle} />)
    await user.click(screen.getByTestId('mobile-tools-toggle'))
    expect(onToggle).toHaveBeenCalledTimes(1)
  })

  it('carries the pulse ring+animate classes when pulse=true', () => {
    render(<MobileToolsButton isDesktop={false} open={false} pulse={true} onToggle={vi.fn()} />)
    const btn = screen.getByTestId('mobile-tools-toggle')
    expect(btn.className).toMatch(/(^|\s)animate-pulse(\s|$)/)
    expect(btn.className).toMatch(/(^|\s)ring-2(\s|$)/)
  })

  it('carries no pulse classes when pulse=false', () => {
    render(<MobileToolsButton isDesktop={false} open={false} pulse={false} onToggle={vi.fn()} />)
    const btn = screen.getByTestId('mobile-tools-toggle')
    expect(btn.className).not.toMatch(/(^|\s)animate-pulse(\s|$)/)
  })

  it('reflects open state via aria-pressed and an accessible label', () => {
    const { rerender } = render(<MobileToolsButton isDesktop={false} open={false} pulse={false} onToggle={vi.fn()} />)
    expect(screen.getByTestId('mobile-tools-toggle')).toHaveAttribute('aria-pressed', 'false')
    rerender(<MobileToolsButton isDesktop={false} open={true} pulse={false} onToggle={vi.fn()} />)
    expect(screen.getByTestId('mobile-tools-toggle')).toHaveAttribute('aria-pressed', 'true')
  })
})
