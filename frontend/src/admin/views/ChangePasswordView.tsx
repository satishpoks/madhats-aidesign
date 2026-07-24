import { useState } from 'react'
import { changePassword } from '../adminApi'

export function ChangePasswordView() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setMsg(null)
    setErr(null)
    setBusy(true)
    try {
      await changePassword(current, next)
      setMsg('Password changed.')
      setCurrent('')
      setNext('')
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : 'Could not change password')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-sm rounded-xl border border-[#e0e1ea] bg-white p-4">
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <h1 className="text-[20px] font-semibold">Change password</h1>
        <label className="flex flex-col gap-1 text-[13px]">
          Current password
          <input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            className="rounded-lg border border-[#e0e1ea] px-3 py-1.5 text-[13px]"
          />
        </label>
        <label className="flex flex-col gap-1 text-[13px]">
          New password
          <input
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            className="rounded-lg border border-[#e0e1ea] px-3 py-1.5 text-[13px]"
          />
        </label>
        {msg && <p className="text-[13px] text-green-600">{msg}</p>}
        {err && <p className="text-[13px] text-red-600">{err}</p>}
        <button
          type="submit"
          disabled={busy || !current || !next}
          className={`self-start rounded-lg bg-[#ff5c00] px-4 py-1.5 text-[13px] font-medium text-white ${busy ? 'opacity-50' : 'hover:bg-[#e65300]'} disabled:opacity-50`}
        >
          {busy ? 'Updating…' : 'Update password'}
        </button>
      </form>
    </div>
  )
}
