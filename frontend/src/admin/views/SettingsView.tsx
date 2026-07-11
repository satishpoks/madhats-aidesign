import { useEffect, useState } from 'react'
import { getSettings, updateSettings, type StudioSettings } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'

export function SettingsView() {
  const [form, setForm] = useState<StudioSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getSettings()
      .then(setForm)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  async function handleSave() {
    if (!form) return
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const next = await updateSettings(form)
      setForm(next)
      setSaved(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  if (!form) return <div className="p-6 text-sm text-[#6b6b80]">Loading…</div>

  return (
    <div className="max-w-xl">
      <h1 className="mb-4 text-xl font-semibold">Studio settings</h1>
      {error && <ErrorBanner message={error} />}
      <div className="space-y-5 rounded-lg border border-[#e0e1ea] bg-white p-6">
        <label className="block">
          <span className="text-[13px] font-medium">Regen edits per session</span>
          <input
            type="number"
            min={0}
            aria-label="Regen edits per session"
            value={form.regen_edits_per_session}
            onChange={(e) =>
              setForm({ ...form, regen_edits_per_session: Number(e.target.value) })
            }
            className="mt-1 w-full rounded border border-[#e0e1ea] px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-[13px] font-medium">Designs per customer per day</span>
          <input
            type="number"
            min={0}
            aria-label="Designs per customer per day"
            value={form.designs_per_customer_per_day}
            onChange={(e) =>
              setForm({ ...form, designs_per_customer_per_day: Number(e.target.value) })
            }
            className="mt-1 w-full rounded border border-[#e0e1ea] px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-[13px] font-medium">FAQ / knowledge (used to answer customer questions)</span>
          <textarea
            rows={6}
            aria-label="FAQ knowledge"
            value={form.faq_knowledge}
            onChange={(e) => setForm({ ...form, faq_knowledge: e.target.value })}
            className="mt-1 w-full rounded border border-[#e0e1ea] px-3 py-2 text-sm"
          />
        </label>
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-[#ff5c00] px-4 py-2 text-sm text-white hover:bg-[#e64f00] disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          {saved && <span className="text-sm text-green-600">Saved</span>}
        </div>
      </div>
    </div>
  )
}
