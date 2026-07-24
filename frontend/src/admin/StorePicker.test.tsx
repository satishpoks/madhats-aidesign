import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StorePicker } from './StorePicker'
import { useAdminStore } from './adminStore'

describe('StorePicker', () => {
  beforeEach(() => useAdminStore.getState().logout())

  it('lists only the profile stores for a store admin', () => {
    useAdminStore.getState().loginWith('bearer', 'jwt', {
      email: 'a@x.com', is_super: false,
      stores: [{ id: 's1', name: 'Store 1', public_key: 'pk1' }],
    })
    render(<StorePicker value="s1" onChange={() => {}} />)
    expect(screen.getByRole('option', { name: 'Store 1' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /all stores/i })).toBeNull()
  })

  it('offers All stores to a super admin when allowAll', () => {
    useAdminStore.getState().loginWith('secret', 's', {
      email: null, is_super: true,
      stores: [{ id: 's1', name: 'Store 1', public_key: 'pk1' }],
    })
    render(<StorePicker value={null} onChange={() => {}} allowAll />)
    expect(screen.getByRole('option', { name: /all stores/i })).toBeInTheDocument()
  })
})
