import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../admin/adminApi', () => ({ listQuoteRequests: vi.fn() }))

import { listQuoteRequests } from '../admin/adminApi'
import { QuoteRequestsView } from '../admin/views/QuoteRequestsView'

// NOTE: deliberately no `beforeEach(mockReset)`. Every test below sets its own
// mockResolvedValue/mockRejectedValue, which replaces the implementation
// outright, so the reset bought nothing — and with it in place vitest reports
// the rejection in "shows an error banner on failure" as an escaped error and
// fails the test even though the banner renders (reproduced in isolation:
// identical test + an EMPTY beforeEach passes, + a mockReset/mockClear one
// fails). That was one of the two long-standing failures in this file; the
// other was the missing Router context.

describe('QuoteRequestsView', () => {
  it('renders quote request rows', async () => {
    vi.mocked(listQuoteRequests).mockResolvedValue([
      {
        lead_id: 'l1', session_id: 's1', name: 'Jane', email: 'jane@x.com', phone: '123',
        notify_by_phone: true, quote_note: 'rush', quote_confirmed_at: '2026-07-01T00:00:00Z',
        product: 'Classic Cap', decoration_type: 'embroidery', placement_zone: 'front',
        quantity: 50, share_token: 'tok',
      },
    ])
    // QuoteRequestsView links each row (useNavigate/<Link>), so it needs a
    // Router in context — these two predated that and had been failing since.
    render(<MemoryRouter><QuoteRequestsView /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('jane@x.com')).toBeInTheDocument())
    expect(screen.getByText('Classic Cap')).toBeInTheDocument()
  })

  it('shows an error banner on failure', async () => {
    vi.mocked(listQuoteRequests).mockRejectedValue(new Error('boom'))
    render(<MemoryRouter><QuoteRequestsView /></MemoryRouter>)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    // waitFor resolves inside the view's .catch — its .finally continuation is
    // still queued. Ending the test there races RTL's cleanup and the rejection
    // escapes as an unhandled error attributed to this test. Let it settle.
    await new Promise((r) => setTimeout(r, 0))
  })

  const baseRow = {
    lead_id: 'l1', session_id: 's1', name: 'Jane', email: 'jane@x.com', phone: '123',
    notify_by_phone: true, quote_note: 'rush', quote_confirmed_at: '2026-07-01T00:00:00Z',
    product: 'Classic Cap', decoration_type: 'embroidery', placement_zone: 'front',
    quantity: 50, share_token: 'tok',
  }

  it('badges a row whose artwork needs its background removed', async () => {
    vi.mocked(listQuoteRequests).mockResolvedValue([
      {
        ...baseRow,
        elements: [
          { kind: 'text', label: 'MADHATS', face: 'front', remove_bg: false },
          { kind: 'logo', label: 'uploaded logo/artwork', face: 'front', remove_bg: true },
        ],
      },
    ])
    render(<MemoryRouter><QuoteRequestsView /></MemoryRouter>)
    expect(await screen.findByText('Remove BG')).toBeInTheDocument()
  })

  it('shows a dash when no element needs background removal', async () => {
    vi.mocked(listQuoteRequests).mockResolvedValue([
      { ...baseRow, elements: [{ kind: 'text', label: 'MADHATS', face: 'front', remove_bg: false }] },
    ])
    render(<MemoryRouter><QuoteRequestsView /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('jane@x.com')).toBeInTheDocument())
    expect(screen.queryByText('Remove BG')).not.toBeInTheDocument()
  })

  it('counts multiple flagged elements', async () => {
    vi.mocked(listQuoteRequests).mockResolvedValue([
      {
        ...baseRow,
        elements: [
          { kind: 'logo', label: 'a', face: 'front', remove_bg: true },
          { kind: 'logo', label: 'b', face: 'back', remove_bg: true },
        ],
      },
    ])
    render(<MemoryRouter><QuoteRequestsView /></MemoryRouter>)
    expect(await screen.findByText('Remove BG ×2')).toBeInTheDocument()
  })
})
