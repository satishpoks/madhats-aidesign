import { describe, it, expect, beforeEach } from 'vitest'
import { useAdminStore } from '../admin/adminStore'

describe('adminStore credential kinds', () => {
  beforeEach(() => {
    sessionStorage.clear()
    useAdminStore.getState().logout()
  })

  it('stores a bearer credential + profile and reports authed', () => {
    useAdminStore.getState().loginWith('bearer', 'jwt-token', {
      email: 'a@x.com', is_super: false, stores: [],
    })
    const s = useAdminStore.getState()
    expect(s.authed).toBe(true)
    expect(s.kind).toBe('bearer')
    expect(s.credential).toBe('jwt-token')
    expect(s.profile?.is_super).toBe(false)
  })

  it('logout clears everything', () => {
    useAdminStore.getState().loginWith('secret', 's3cr3t', { email: null, is_super: true, stores: [] })
    useAdminStore.getState().logout()
    expect(useAdminStore.getState().authed).toBe(false)
    expect(useAdminStore.getState().credential).toBeNull()
  })
})
