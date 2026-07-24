import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

import { RequireAuth } from '../admin/RequireAuth'
import { useAdminStore } from '../admin/adminStore'

beforeEach(() => {
  useAdminStore.getState().logout()
})

// Rendered inside a matching <Routes> tree, the same way the real app mounts
// RequireAuth — rendering it bare (no <Routes>) never unmounts it once
// Navigate fires, which re-triggers Navigate every commit and infinite-loops.
function renderGuarded() {
  return render(
    <MemoryRouter initialEntries={['/admin/stores']}>
      <Routes>
        <Route path="/admin/login" element={<div>login page</div>} />
        <Route
          path="/admin/stores"
          element={
            <RequireAuth>
              <div>secret content</div>
            </RequireAuth>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RequireAuth', () => {
  it('redirects to the login route when not authed', () => {
    renderGuarded()
    expect(screen.queryByText('secret content')).not.toBeInTheDocument()
    expect(screen.getByText('login page')).toBeInTheDocument()
  })

  it('renders children when authed', () => {
    useAdminStore.getState().loginWith('bearer', 'jwt', { email: 'a@x.com', is_super: false, stores: [] })
    renderGuarded()
    expect(screen.getByText('secret content')).toBeInTheDocument()
  })
})
