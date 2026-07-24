import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { UsersView } from './UsersView'
import * as api from '../adminApi'

vi.mock('../adminApi')

describe('UsersView', () => {
  beforeEach(() => vi.clearAllMocks())

  it('lists admin users and their assigned stores', async () => {
    vi.mocked(api.listUsers).mockResolvedValue([
      { id: 'u1', email: 'ops@x.com', is_super: false, status: 'active', stores: [{ id: 's1', name: 'Store 1' }] },
    ])
    vi.mocked(api.listStores).mockResolvedValue([
      { id: 's1', slug: 's1', name: 'Store 1', public_key: 'pk', shopify_domain: null, status: 'active' },
    ])
    render(
      <MemoryRouter>
        <UsersView />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('ops@x.com')).toBeInTheDocument())
    const table = screen.getByRole('table')
    expect(within(table).getByText(/Store 1/)).toBeInTheDocument()
  })

  it('creates a user', async () => {
    vi.mocked(api.listUsers).mockResolvedValue([])
    vi.mocked(api.listStores).mockResolvedValue([
      { id: 's1', slug: 's1', name: 'Store 1', public_key: 'pk', shopify_domain: null, status: 'active' },
    ])
    vi.mocked(api.createUser).mockResolvedValue({ id: 'u2', email: 'new@x.com', is_super: false, status: 'active', stores: [] })
    render(
      <MemoryRouter>
        <UsersView />
      </MemoryRouter>,
    )
    await waitFor(() => expect(api.listUsers).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'new@x.com' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pw' } })
    fireEvent.click(screen.getByLabelText(/Store 1/i))
    fireEvent.click(screen.getByRole('button', { name: /create user/i }))
    await waitFor(() => expect(api.createUser).toHaveBeenCalledWith({
      email: 'new@x.com', password: 'pw', is_super: false, store_ids: ['s1'],
    }))
  })
})
