import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QuoteRequestsView } from './QuoteRequestsView'
import * as api from '../adminApi'

describe('QuoteRequestsView', () => {
  beforeEach(() => {
    vi.spyOn(api, 'listQuoteRequests').mockResolvedValue([
      {
        lead_id: 'lead-1', session_id: 'sess-1', reference_code: 'MH-BCDFGH',
        name: 'Ann', email: 'ann@example.com', product: 'Snapback',
        decoration_type: 'embroidery', quantity: 24, needed_by: '2-4 weeks',
        purpose: 'team', quote_confirmed_at: null,
      } as unknown as api.QuoteRequest,
    ])
  })

  it('shows the tracking reference', async () => {
    render(<MemoryRouter><QuoteRequestsView /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('MH-BCDFGH')).toBeInTheDocument())
  })
})
