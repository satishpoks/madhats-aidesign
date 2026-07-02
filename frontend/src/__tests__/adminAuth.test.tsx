import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../admin/adminApi', () => ({
  validateSecret: vi.fn(),
}))

import { validateSecret } from '../admin/adminApi'
import { AdminLogin } from '../admin/AdminLogin'
import { RequireAuth } from '../admin/RequireAuth'
import { useAdminStore } from '../admin/adminStore'

beforeEach(() => {
  useAdminStore.getState().logout()
  vi.mocked(validateSecret).mockReset()
})

describe('AdminLogin', () => {
  it('stores the secret and sets authed on a valid secret', async () => {
    vi.mocked(validateSecret).mockResolvedValue(true)
    render(
      <MemoryRouter>
        <AdminLogin />
      </MemoryRouter>,
    )
    fireEvent.change(screen.getByLabelText(/admin secret/i), { target: { value: 'good-secret' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => expect(useAdminStore.getState().authed).toBe(true))
    expect(useAdminStore.getState().secret).toBe('good-secret')
  })

  it('shows an error and does not authenticate on an invalid secret', async () => {
    vi.mocked(validateSecret).mockResolvedValue(false)
    render(
      <MemoryRouter>
        <AdminLogin />
      </MemoryRouter>,
    )
    fireEvent.change(screen.getByLabelText(/admin secret/i), { target: { value: 'bad' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => expect(screen.getByText(/invalid admin secret/i)).toBeInTheDocument())
    expect(useAdminStore.getState().authed).toBe(false)
  })
})

describe('RequireAuth', () => {
  it('redirects to the login route when not authed', () => {
    render(
      <MemoryRouter initialEntries={['/admin/stores']}>
        <RequireAuth>
          <div>secret content</div>
        </RequireAuth>
      </MemoryRouter>,
    )
    expect(screen.queryByText('secret content')).not.toBeInTheDocument()
  })

  it('renders children when authed', () => {
    useAdminStore.getState().login('s')
    render(
      <MemoryRouter initialEntries={['/admin/stores']}>
        <RequireAuth>
          <div>secret content</div>
        </RequireAuth>
      </MemoryRouter>,
    )
    expect(screen.getByText('secret content')).toBeInTheDocument()
  })
})
