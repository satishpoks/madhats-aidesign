import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAdminStore } from './adminStore'
import { login as apiLogin, fetchMe, ApiError } from './adminApi'

export function AdminLogin() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [secret, setSecret] = useState('')
  const [useSecret, setUseSecret] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const loginWith = useAdminStore((s) => s.loginWith)
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: { pathname: string } } | null)?.from?.pathname ?? '/admin/submissions'

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (useSecret) {
        // Env super admin: validate the secret via /admin/auth/me.
        loginWith('secret', secret, null)
        const profile = await fetchMe()
        loginWith('secret', secret, profile)
        navigate(from, { replace: true })
      } else {
        const { token, profile } = await apiLogin(email, password)
        loginWith('bearer', token, profile)
        navigate(from, { replace: true })
      }
    } catch (err) {
      useAdminStore.getState().logout()
      setError(err instanceof ApiError ? err.detail : 'Could not sign in — try again')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <form onSubmit={onSubmit} className="w-full max-w-sm bg-white rounded-lg shadow p-6 space-y-4">
        <h1 className="text-lg font-semibold text-gray-900">MadHats Admin</h1>
        {!useSecret ? (
          <>
            <label className="block text-sm font-medium text-gray-700">
              Email
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-sm font-medium text-gray-700">
              Password
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
          </>
        ) : (
          <label className="block text-sm font-medium text-gray-700">
            Admin secret
            <input
              type="password"
              autoComplete="off"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </label>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={busy || (useSecret ? secret.length === 0 : email.length === 0 || password.length === 0)}
          className="w-full rounded-lg bg-[#ff5c00] text-white py-2 text-sm font-medium hover:bg-[#e64f00] disabled:opacity-50"
        >
          {busy ? 'Checking…' : 'Sign in'}
        </button>
        <button
          type="button"
          onClick={() => { setUseSecret(!useSecret); setError(null) }}
          className="w-full text-xs text-gray-500 hover:text-gray-700"
        >
          {useSecret ? 'Use email + password instead' : 'Use admin secret instead'}
        </button>
      </form>
    </div>
  )
}
