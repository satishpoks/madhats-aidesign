import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

vi.mock('../admin/adminApi', () => ({ listQuoteRequests: vi.fn() }))

import { listQuoteRequests } from '../admin/adminApi'
import { QuoteRequestsView } from '../admin/views/QuoteRequestsView'

beforeEach(() => vi.mocked(listQuoteRequests).mockReset())

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
    render(<QuoteRequestsView />)
    await waitFor(() => expect(screen.getByText('jane@x.com')).toBeInTheDocument())
    expect(screen.getByText('Classic Cap')).toBeInTheDocument()
  })

  it('shows an error banner on failure', async () => {
    vi.mocked(listQuoteRequests).mockRejectedValue(new Error('boom'))
    render(<QuoteRequestsView />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})
