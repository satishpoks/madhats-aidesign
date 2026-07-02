import { create } from 'zustand'

const STORAGE_KEY = 'mh_admin_secret'

function readStored(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

interface AdminState {
  secret: string | null
  authed: boolean
  login: (secret: string) => void
  logout: () => void
}

export const useAdminStore = create<AdminState>((set) => {
  const stored = readStored()
  return {
    secret: stored,
    authed: stored !== null,
    login: (secret: string) => {
      try {
        sessionStorage.setItem(STORAGE_KEY, secret)
      } catch {
        // sessionStorage unavailable — keep in-memory only
      }
      set({ secret, authed: true })
    },
    logout: () => {
      try {
        sessionStorage.removeItem(STORAGE_KEY)
      } catch {
        // ignore
      }
      set({ secret: null, authed: false })
    },
  }
})

/** Non-hook accessors for use inside adminApi (outside React render). */
export function getSecret(): string | null {
  return useAdminStore.getState().secret
}

export function logout(): void {
  useAdminStore.getState().logout()
}
