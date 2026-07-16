import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { BrandingView } from '../admin/views/BrandingView'
import * as api from '../admin/adminApi'

vi.mock('../admin/adminApi', async (orig) => {
  const actual = await orig<typeof api>()
  return {
    ...actual,
    listStores: vi.fn(async () => [{ id: 's1', slug: 'acme', name: 'Acme', public_key: 'k', shopify_domain: null, status: 'active' }]),
    getStore: vi.fn(async () => ({ id: 's1', slug: 'acme', name: 'Acme', brand: { primary_colour: '#123456', menu_items: [] } })),
    updateStoreBrand: vi.fn(async (_id: string, brand) => ({ id: 's1', slug: 'acme', name: 'Acme', brand })),
    uploadStoreLogo: vi.fn(async () => ({ logo_url: 'http://x/logo.png' })),
  }
})

function renderView() {
  return render(<MemoryRouter initialEntries={['/admin/branding?store=s1']}><BrandingView /></MemoryRouter>)
}

describe('BrandingView canvas intro', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows a canvas intro field', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalledWith('s1'))
    expect(screen.getByLabelText(/canvas intro/i)).toBeInTheDocument()
  })
})
