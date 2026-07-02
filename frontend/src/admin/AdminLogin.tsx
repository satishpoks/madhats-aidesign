import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAdminStore } from './adminStore'
import { validateSecret } from './adminApi'

export function AdminLogin() {
  const [secret, setSecret] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const login = useAdminStore((s) => s.login)
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: { pathname: string } } | null)?.from?.pathname ?? '/admin/submissions'

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const valid = await validateSecret(secret)
      if (valid) {
        login(secret)
        navigate(from, { replace: true })
      } else {
        setError('Invalid admin secret')
      }
    } catch {
      setError('Could not reach the server — try again')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <form onSubmit={onSubmit} className="w-full max-w-sm bg-white rounded-lg shadow p-6 space-y-4">
        <h1 className="text-lg font-semibold text-gray-900">MadHats Admin</h1>
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
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={busy || secret.length === 0}
          className="w-full rounded-lg bg-[#ff5c00] text-white py-2 text-sm font-medium hover:bg-[#e64f00] disabled:opacity-50"
        >
          {busy ? 'Checking…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
