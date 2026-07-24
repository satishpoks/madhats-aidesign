import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AdminLogin } from './AdminLogin'
import * as api from './adminApi'
import { useAdminStore } from './adminStore'

vi.mock('./adminApi')

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
})
