import { create } from 'zustand'

const CRED_KEY = 'mh_admin_cred'
const KIND_KEY = 'mh_admin_kind'

export type CredKind = 'bearer' | 'secret'

export interface Profile {
  email: string | null
  is_super: boolean
  stores: { id: string; name: string; public_key: string }[]
}

function read(key: string): string | null {
  try {
    return sessionStorage.getItem(key)
  } catch {
    return null
  }
}

interface AdminState {
  kind: CredKind
  credential: string | null
  profile: Profile | null
  authed: boolean
  loginWith: (kind: CredKind, credential: string, profile: Profile | null) => void
  setProfile: (profile: Profile) => void
  logout: () => void
}

export const useAdminStore = create<AdminState>((set) => {
  const credential = read(CRED_KEY)
  const kind = (read(KIND_KEY) as CredKind) || 'bearer'
  return {
    kind,
    credential,
    profile: null,
    authed: credential !== null,
    loginWith: (k, cred, profile) => {
      try {
        sessionStorage.setItem(CRED_KEY, cred)
        sessionStorage.setItem(KIND_KEY, k)
      } catch {
        // in-memory only
      }
      set({ kind: k, credential: cred, profile, authed: true })
    },
    setProfile: (profile) => set({ profile }),
    logout: () => {
      try {
        sessionStorage.removeItem(CRED_KEY)
        sessionStorage.removeItem(KIND_KEY)
      } catch {
        // ignore
      }
      set({ kind: 'bearer', credential: null, profile: null, authed: false })
    },
  }
})

/** Non-hook accessors for use inside adminApi (outside React render). */
export function getCredential(): { kind: CredKind; credential: string | null } {
  const s = useAdminStore.getState()
  return { kind: s.kind, credential: s.credential }
}

export function logout(): void {
  useAdminStore.getState().logout()
}
