import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../admin/adminApi', () => ({
  listStores: vi.fn(),
  createStore: vi.fn(),
  syncStore: vi.fn(),
}))

import { listStores, createStore, syncStore } from '../admin/adminApi'
import { StoresView } from '../admin/views/StoresView'

const store = { id: 'st-1', slug: 'madhats', name: 'MadHats', public_key: 'mh_pk_x', shopify_domain: null, status: 'active', created_at: '2026-07-01T00:00:00Z' }

beforeEach(() => {
  vi.mocked(listStores).mockReset()
  vi.mocked(createStore).mockReset()
  vi.mocked(syncStore).mockReset()
})

describe('StoresView', () => {
  it('lists stores', async () => {
    vi.mocked(listStores).mockResolvedValue([store])
    render(<StoresView />)
    await waitFor(() => expect(screen.getByText('madhats')).toBeInTheDocument())
    expect(screen.getByText('mh_pk_x')).toBeInTheDocument()
  })

  it('creates a store from the form', async () => {
    vi.mocked(listStores).mockResolvedValue([])
    vi.mocked(createStore).mockResolvedValue(store)
    render(<StoresView />)
    await waitFor(() => expect(listStores).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText(/slug/i), { target: { value: 'madhats' } })
    fireEvent.change(screen.getByLabelText(/^name/i), { target: { value: 'MadHats' } })
    fireEvent.click(screen.getByRole('button', { name: /create store/i }))
    await waitFor(() => expect(createStore).toHaveBeenCalledWith(
      expect.objectContaining({ slug: 'madhats', name: 'MadHats' }),
    ))
  })

  it('syncs a store and shows counts', async () => {
    vi.mocked(listStores).mockResolvedValue([store])
    vi.mocked(syncStore).mockResolvedValue({ fetched: 10, imported: 8, skipped: 2 })
    render(<StoresView />)
    await waitFor(() => expect(screen.getByText('madhats')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /sync/i }))
    await waitFor(() => expect(syncStore).toHaveBeenCalledWith('st-1'))
    await waitFor(() => expect(screen.getByText(/imported 8/i)).toBeInTheDocument())
  })
})
