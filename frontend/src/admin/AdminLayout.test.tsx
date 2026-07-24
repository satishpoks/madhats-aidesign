import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AdminLayout } from './AdminLayout'
import { useAdminStore } from './adminStore'

function renderWithProfile(is_super: boolean) {
  useAdminStore.getState().loginWith('bearer', 'jwt', { email: 'a@x.com', is_super, stores: [] })
  return render(
    <MemoryRouter>
      <AdminLayout />
    </MemoryRouter>,
  )
}

describe('AdminLayout nav gating', () => {
  beforeEach(() => useAdminStore.getState().logout())

  it('hides super-only nav for a store admin', () => {
    renderWithProfile(false)
    expect(screen.queryByRole('link', { name: /users/i })).toBeNull()
    expect(screen.queryByRole('link', { name: /diagnostics/i })).toBeNull()
  })

  it('shows super-only nav for a super admin', () => {
    renderWithProfile(true)
    expect(screen.getByRole('link', { name: /users/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /diagnostics/i })).toBeInTheDocument()
  })
})
