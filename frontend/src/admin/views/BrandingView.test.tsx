import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { BrandingView } from './BrandingView'
import * as api from '../adminApi'

vi.mock('../adminApi', async (orig) => {
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

describe('BrandingView', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads and shows the store primary colour', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalledWith('s1'))
    expect(await screen.findByDisplayValue('#123456')).toBeInTheDocument()
  })

  it('blocks a 6th menu item', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    // add 5 rows -> the "Add menu item" control disables at 5
    for (let i = 0; i < 5; i++) fireEvent.click(screen.getByRole('button', { name: /add menu item/i }))
    expect(screen.getByRole('button', { name: /add menu item/i })).toBeDisabled()
  })

  it('rejects a non-http url on save', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /add menu item/i }))
    fireEvent.change(screen.getByPlaceholderText(/label/i), { target: { value: 'Bad' } })
    fireEvent.change(screen.getByPlaceholderText(/https/i), { target: { value: 'javascript:alert(1)' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    expect(await screen.findByText(/http\(s\)/i)).toBeInTheDocument()
    expect(api.updateStoreBrand).not.toHaveBeenCalled()
  })
})
