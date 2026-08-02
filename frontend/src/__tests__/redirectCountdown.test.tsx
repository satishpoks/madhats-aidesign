import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, act, fireEvent } from '@testing-library/react'
import { useChatStore } from '../store/chatStore'
import { useBrandStore } from '../store/brandStore'
import { RedirectCountdown } from '../components/CustomiseStudio/RedirectCountdown'

const assign = vi.fn()

beforeEach(() => {
  vi.useFakeTimers()
  assign.mockClear()
  // jsdom's window.location is not assignable; replace just the method we call.
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...window.location, assign },
  })
  useChatStore.getState().reset()
  useBrandStore.setState({ brand: {}, loaded: true } as never)
})

afterEach(() => {
  vi.useRealTimers()
})

function open(seconds?: number) {
  useBrandStore.setState({
    brand: { redirect_url: 'https://madhats.com.au', redirect_seconds: seconds },
  } as never)
  // Backend-owned signal, not the raw chat state — see the "does not open for
  // a v1 canvas session" test below for why that distinction matters.
  useChatStore.setState({ chatState: 'quote_requested', sessionEnded: true } as never)
  return render(<RedirectCountdown />)
}

function tick(seconds: number) {
  act(() => { vi.advanceTimersByTime(seconds * 1000) })
}

describe('RedirectCountdown', () => {
  it('renders nothing before the session ends', () => {
    useBrandStore.setState({ brand: { redirect_url: 'https://madhats.com.au' } } as never)
    useChatStore.setState({ chatState: 'ask_quantity' } as never)
    const { container } = render(<RedirectCountdown />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when the store configured no redirect', () => {
    // Absence of the URL is the off switch — an unconfigured store must behave
    // exactly as it did before this feature existed.
    useChatStore.setState({ chatState: 'quote_requested', sessionEnded: true } as never)
    const { container } = render(<RedirectCountdown />)
    expect(container).toBeEmptyDOMElement()
    tick(60)
    expect(assign).not.toHaveBeenCalled()
  })

  it('does not open for a v1 canvas session resting at quote_requested', () => {
    // `quote_requested` is a state STRING shared with v1, where it is an
    // answerable yes/no gate, not an ending — the backend only sets
    // `sessionEnded` true for a v2 canvas session. Gating on the raw chat
    // state (the pre-fix behaviour) yanked a v1 customer to the shop over a
    // question they could still answer.
    useBrandStore.setState({ brand: { redirect_url: 'https://madhats.com.au' } } as never)
    useChatStore.setState({ chatState: 'quote_requested', sessionEnded: false } as never)
    const { container } = render(<RedirectCountdown />)
    expect(container).toBeEmptyDOMElement()
    tick(60)
    expect(assign).not.toHaveBeenCalled()
  })

  it('never navigates to a non-http(s) redirect_url', () => {
    // Defence in depth: even if a stored brand somehow carries an unsafe
    // scheme (e.g. a pre-validation row, or a future write path that forgets
    // the admin-route guard), the component must not treat it as configured.
    useBrandStore.setState({
      brand: { redirect_url: 'javascript:alert(1)', redirect_seconds: 5 },
    } as never)
    useChatStore.setState({ chatState: 'quote_requested', sessionEnded: true } as never)
    const { container } = render(<RedirectCountdown />)
    expect(container).toBeEmptyDOMElement()
    tick(60)
    expect(assign).not.toHaveBeenCalled()
  })

  it('counts down from the configured seconds and then redirects', () => {
    open(10)
    expect(screen.getByTestId('redirect-countdown')).toHaveTextContent('10')
    tick(4)
    expect(screen.getByTestId('redirect-countdown')).toHaveTextContent('6')
    expect(assign).not.toHaveBeenCalled()
    tick(6)
    expect(assign).toHaveBeenCalledWith('https://madhats.com.au')
  })

  it('falls back to 30 seconds when the store set no duration', () => {
    open(undefined)
    expect(screen.getByTestId('redirect-countdown')).toHaveTextContent('30')
  })

  it('redirects immediately on "Go to the shop now"', () => {
    // fireEvent, not userEvent: userEvent's internal pointer/wait machinery
    // deadlocks against vi.useFakeTimers() in this environment regardless of
    // the `delay`/`advanceTimers` config (verified — real timers alone let
    // userEvent resolve instantly, so this is an environment quirk, not a
    // component bug). fireEvent.click is a synchronous DOM dispatch and
    // exercises the exact same onClick handler.
    open(30)
    fireEvent.click(screen.getByRole('button', { name: /go to the shop now/i }))
    expect(assign).toHaveBeenCalledWith('https://madhats.com.au')
  })

  it('cancels for good on "Stay here" — no later tick may fire it', () => {
    // The interval must be cleared, not merely hidden. A dialog that closes but
    // keeps ticking would yank the customer away from the design they chose to
    // stay and look at.
    open(10)
    fireEvent.click(screen.getByRole('button', { name: /stay here/i }))
    expect(screen.queryByTestId('redirect-countdown')).not.toBeInTheDocument()
    tick(120)
    expect(assign).not.toHaveBeenCalled()
  })

  it('never fires after unmount', () => {
    const { unmount } = open(10)
    unmount()
    tick(60)
    expect(assign).not.toHaveBeenCalled()
  })
})
