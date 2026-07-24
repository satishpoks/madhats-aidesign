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
    expect(await screen.findByRole('textbox', { name: 'primary_colour' })).toHaveValue('#123456')
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

  // --- Workstream D: the "Flow steps" card ------------------------------------

  it('never surfaces a dependency-locked step', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    expect(await screen.findByText('Flow steps')).toBeInTheDocument()
    // Only the safe subset is offered; email/decoration/finalize are locked.
    // Three since workstream B's `needed_by` joined the configurable subset.
    expect(screen.getAllByRole('checkbox')).toHaveLength(3)
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument()
  })

  it('persists a reorder into brand.canvas_flow', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.click(await screen.findByRole('button', { name: /move what is the hat for\? up/i }))
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(api.updateStoreBrand).toHaveBeenCalled())
    const brand = vi.mocked(api.updateStoreBrand).mock.calls[0][1]
    // Default order is quantity -> needed_by -> purpose (workstream B inserted
    // needed_by between them), so one "up" click on purpose swaps it with
    // needed_by rather than putting it first. Still a genuine reorder off the
    // default, which is what this test asserts is persisted.
    expect(brand.canvas_flow?.steps).toEqual([
      { id: 'ask_quantity', enabled: true },
      { id: 'ask_purpose', enabled: true },
      { id: 'needed_by', enabled: true },
    ])
  })

  it('persists a disabled step', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.click(await screen.findByRole('checkbox', { name: /what is the hat for\? enabled/i }))
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(api.updateStoreBrand).toHaveBeenCalled())
    const brand = vi.mocked(api.updateStoreBrand).mock.calls[0][1]
    expect(brand.canvas_flow?.steps).toContainEqual({ id: 'ask_purpose', enabled: false })
  })
})
