import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AdminLogin } from './AdminLogin'
import * as api from './adminApi'
import { useAdminStore } from './adminStore'

vi.mock('./adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./adminApi')>()
  return { ...actual, login: vi.fn(), fetchMe: vi.fn() }
})

describe('AdminLogin', () => {
  beforeEach(() => {
    useAdminStore.getState().logout()
    vi.clearAllMocks()
  })

  it('logs in with email + password', async () => {
    vi.mocked(api.login).mockResolvedValue({
      token: 'jwt', profile: { email: 'a@x.com', is_super: false, stores: [] },
    })
    render(
      <MemoryRouter>
        <AdminLogin />
      </MemoryRouter>,
    )
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'a@x.com' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => expect(useAdminStore.getState().credential).toBe('jwt'))
    expect(useAdminStore.getState().kind).toBe('bearer')
  })

  it('rolls back to logged-out state when secret-mode validation fails', async () => {
    vi.mocked(api.fetchMe).mockRejectedValue(new api.ApiError(401, 'Invalid admin secret'))
    render(
      <MemoryRouter>
        <AdminLogin />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: /use admin secret instead/i }))
    fireEvent.change(screen.getByLabelText(/admin secret/i), { target: { value: 'wrong-secret' } })
    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }))
    await waitFor(() => expect(screen.getByText(/invalid admin secret/i)).toBeInTheDocument())
    expect(useAdminStore.getState().authed).toBe(false)
    expect(useAdminStore.getState().credential).toBeNull()
  })

  it('shows the error and stays logged out when email login fails', async () => {
    vi.mocked(api.login).mockRejectedValue(new api.ApiError(401, 'Invalid email or password'))
    render(
      <MemoryRouter>
        <AdminLogin />
      </MemoryRouter>,
    )
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'a@x.com' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }))
    await waitFor(() => expect(screen.getByText(/invalid email or password/i)).toBeInTheDocument())
    expect(useAdminStore.getState().authed).toBe(false)
  })

  it('disables submit until email + password are both filled', () => {
    render(
      <MemoryRouter>
        <AdminLogin />
      </MemoryRouter>,
    )
    const submit = screen.getByRole('button', { name: /^sign in$/i })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'a@x.com' } })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pw' } })
    expect(submit).not.toBeDisabled()
  })
})
