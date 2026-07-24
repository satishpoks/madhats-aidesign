import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getStore, updateStoreBrand, uploadStoreLogo, type FullStore } from '../adminApi'
import type { Brand, MenuItem, FlowStep } from '../../lib/types'
import { ErrorBanner } from '../components/ErrorBanner'
import { useStores } from './hatTypes/shared'

const HEX = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/
const MAX_MENU = 5
const MAX_LABEL_LEN = 40

// The safe, admin-configurable subset — mirrors the backend's
// canvas_steps.CONFIGURABLE_STEP_IDS. Every other v2 step is dependency-locked
// and is deliberately never surfaced here; the server rejects a locked id
// regardless, so this list is UX, not the guard.
//
// `needed_by` is listed because workstream B's step is now in the backend
// registry, which makes it configurable automatically (CONFIGURABLE_STEP_IDS is
// REGISTRY intersected with the safe-subset names). Keep this array in step
// with that intersection: listing an id the backend does not accept makes the
// first toggle save fail with a 400, and omitting one the backend DOES accept
// silently hides a step admins are entitled to configure.
const FLOW_STEPS: { id: string; label: string }[] = [
  { id: 'ask_quantity', label: 'How many caps?' },
  { id: 'needed_by', label: 'When do you need these by?' },
  { id: 'ask_purpose', label: 'What is the hat for?' },
]

function validate(brand: Brand): string | null {
  for (const [k, v] of Object.entries(brand)) {
    if (k.endsWith('_colour') || k === 'header_bg' || k === 'header_text') {
      if (v && !HEX.test(v as string)) return `${k} must be a hex colour`
    }
  }
  for (const m of brand.menu_items ?? []) {
    if (!m.label.trim()) return 'Every menu item needs a label'
    if (m.label.trim().length > MAX_LABEL_LEN) return 'Menu labels must be 40 characters or fewer'
    if (!/^https?:\/\//i.test(m.url)) return 'Menu links must be full http(s) URLs'
  }
  return null
}

export function BrandingView() {
  const { stores, error: storesError } = useStores()
  const [params, setParams] = useSearchParams()
  const storeId = params.get('store') ?? ''
  const [brand, setBrand] = useState<Brand>({})
  const [logoUrl, setLogoUrl] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (stores.length > 0 && !stores.some(s => s.id === storeId)) {
      setParams({ store: stores[0].id }, { replace: true })
    }
  }, [storeId, stores, setParams])

  useEffect(() => {
    if (!storeId) return
    getStore(storeId)
      .then((s: FullStore) => { setBrand(s.brand ?? {}); setLogoUrl(s.brand?.logo_url ?? '') })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load store'))
  }, [storeId])

  function setField(k: keyof Brand, v: string) { setBrand(b => ({ ...b, [k]: v })); setSaved(false) }
  function setMenu(items: MenuItem[]) { setBrand(b => ({ ...b, menu_items: items })); setSaved(false) }
  const menu = brand.menu_items ?? []

  // Compose the current view: configured order first, then any step the store
  // never mentioned (default order, enabled) — the same rule the backend
  // compose applies. Unknown ids in the stored config are filtered out so a
  // step this build doesn't know about can never be echoed back on save.
  const configured = (brand.canvas_flow?.steps ?? []).filter(
    s => FLOW_STEPS.some(f => f.id === s.id))
  const flow: FlowStep[] = [
    ...configured,
    ...FLOW_STEPS.filter(f => !configured.some(s => s.id === f.id))
      .map(f => ({ id: f.id, enabled: true })),
  ]
  const labelOf = (id: string) => FLOW_STEPS.find(f => f.id === id)?.label ?? id
  function setFlow(steps: FlowStep[]) {
    setBrand(b => ({ ...b, canvas_flow: { steps } })); setSaved(false)
  }
  function toggleStep(i: number) {
    setFlow(flow.map((s, j) => j === i ? { ...s, enabled: !s.enabled } : s))
  }
  function moveStep(i: number, dir: -1 | 1) {
    const j = i + dir
    if (j < 0 || j >= flow.length) return
    const next = [...flow]
    ;[next[i], next[j]] = [next[j], next[i]]
    setFlow(next)
  }

  async function onLogo(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !storeId) return
    setBusy(true); setError(null)
    try {
      const { logo_url } = await uploadStoreLogo(storeId, file)
      setLogoUrl(logo_url); setBrand(b => ({ ...b, logo_url }))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Logo upload failed')
    } finally { setBusy(false); e.target.value = '' }
  }

  async function onSave() {
    const msg = validate(brand)
    if (msg) { setError(msg); return }
    setBusy(true); setError(null)
    try {
      // logo_url stored via upload already; strip the proxied absolute URL so we
      // don't overwrite the storage path with a signed URL. Backend keeps it.
      const { logo_url: _omit, ...rest } = brand
      await updateStoreBrand(storeId, rest)
      setSaved(true)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally { setBusy(false) }
  }

  return (
    <div className="flex flex-col gap-5 max-w-[720px]">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[20px] font-semibold">Branding</h1>
        <select
          value={storeId}
          onChange={e => setParams({ store: e.target.value }, { replace: true })}
          className="rounded-lg border border-[#e0e1ea] bg-white px-3 py-1.5 text-[13px]"
          aria-label="Store"
        >
          {stores.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>

      {(storesError || error) && <ErrorBanner message={storesError || error || ''} />}

      {/* Live preview */}
      <div className="rounded-xl border border-[#e0e1ea] overflow-hidden">
        <div className="px-4 py-3 flex items-center gap-3"
             style={{ background: brand.header_bg || '#fff', color: brand.header_text || '#1a1a2e' }}>
          {logoUrl ? <img src={logoUrl} alt="logo" className="h-7" /> : <strong>{stores.find(s => s.id === storeId)?.name}</strong>}
          <span className="ml-auto flex gap-3 text-[13px]">
            {menu.map((m, i) => <span key={i}>{m.label || '—'}</span>)}
          </span>
        </div>
        <div className="p-4 bg-white">
          <button className="rounded-lg px-4 py-2 text-white text-[13px] font-medium"
                  style={{ background: brand.primary_colour || '#ff5c00' }}>Sample button</button>
        </div>
      </div>

      {/* Logo */}
      <div className="flex items-center gap-3 rounded-xl border border-[#e0e1ea] bg-white p-4">
        <label className={`cursor-pointer rounded-lg bg-[#ff5c00] px-4 py-1.5 text-[13px] font-medium text-white ${busy ? 'opacity-50' : ''}`}>
          {busy ? 'Uploading…' : 'Upload logo'}
          <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" onChange={onLogo} disabled={busy} className="sr-only" />
        </label>
        <span className="text-[12px] text-[#9a9ab0]">PNG/JPG/GIF/WebP · max 10 MB</span>
      </div>

      {/* Colours */}
      <div className="grid grid-cols-3 gap-4 rounded-xl border border-[#e0e1ea] bg-white p-4">
        {(['primary_colour', 'header_bg', 'header_text'] as const).map(k => (
          <label key={k} className="flex flex-col gap-1 text-[12px] text-[#6b6b80]">
            {k.replace('_', ' ')}
            <span className="flex items-center gap-2">
              <input type="color" value={HEX.test((brand[k] as string) || '') ? (brand[k] as string) : '#ffffff'}
                     onChange={e => setField(k, e.target.value)}
                     aria-label={`${k} picker`}
                     className="h-8 w-10 rounded border border-[#e0e1ea]" />
              <input type="text" value={(brand[k] as string) || ''} onChange={e => setField(k, e.target.value)}
                     aria-label={k}
                     placeholder="#RRGGBB" className="w-24 rounded border border-[#e0e1ea] px-2 py-1 text-[12px]" />
            </span>
          </label>
        ))}
      </div>

      {/* Canvas intro */}
      <label className="flex flex-col gap-1 rounded-xl border border-[#e0e1ea] bg-white p-4 text-[12px] text-[#6b6b80]">
        <span className="text-sm text-textMuted">Canvas intro (shown after the customer's name)</span>
        <textarea
          aria-label="Canvas intro"
          maxLength={600}
          value={brand.canvas_intro ?? ''}
          onChange={e => setField('canvas_intro', e.target.value)}
          className="mt-1 w-full rounded-lg border border-[#e0e1ea] bg-white px-3 py-2 text-sm"
          rows={4}
        />
      </label>

      {/* Flow steps (V3 — reorder/disable the safe subset) */}
      <div className="flex flex-col gap-2 rounded-xl border border-[#e0e1ea] bg-white p-4">
        <span className="text-[13px] font-medium">Flow steps</span>
        <span className="text-[12px] text-[#9a9ab0]">
          Reorder or switch off these questions. Everything else in the flow is fixed.
        </span>
        {flow.map((s, i) => (
          <div key={s.id} className="flex items-center gap-2">
            <label className="flex flex-1 items-center gap-2 text-[13px]">
              <input type="checkbox" checked={s.enabled}
                     onChange={() => toggleStep(i)}
                     aria-label={`${labelOf(s.id)} enabled`} />
              <span className={s.enabled ? '' : 'text-[#9a9ab0] line-through'}>{labelOf(s.id)}</span>
            </label>
            <button onClick={() => moveStep(i, -1)} disabled={i === 0}
                    aria-label={`Move ${labelOf(s.id)} up`}
                    className="rounded border border-[#e0e1ea] px-2 text-[12px] disabled:opacity-40">↑</button>
            <button onClick={() => moveStep(i, 1)} disabled={i === flow.length - 1}
                    aria-label={`Move ${labelOf(s.id)} down`}
                    className="rounded border border-[#e0e1ea] px-2 text-[12px] disabled:opacity-40">↓</button>
          </div>
        ))}
      </div>

      {/* Menu */}
      <div className="flex flex-col gap-2 rounded-xl border border-[#e0e1ea] bg-white p-4">
        <div className="flex items-center justify-between">
          <span className="text-[13px] font-medium">Main menu ({menu.length}/{MAX_MENU})</span>
          <button
            onClick={() => setMenu([...menu, { label: '', url: '' }])}
            disabled={menu.length >= MAX_MENU}
            className="rounded-lg border border-[#e0e1ea] px-3 py-1 text-[12px] disabled:opacity-40"
          >Add menu item</button>
        </div>
        {menu.map((m, i) => (
          <div key={i} className="flex gap-2">
            <input value={m.label} placeholder="Label"
                   onChange={e => setMenu(menu.map((x, j) => j === i ? { ...x, label: e.target.value } : x))}
                   className="w-40 rounded border border-[#e0e1ea] px-2 py-1 text-[13px]" />
            <input value={m.url} placeholder="https://…"
                   onChange={e => setMenu(menu.map((x, j) => j === i ? { ...x, url: e.target.value } : x))}
                   className="flex-1 rounded border border-[#e0e1ea] px-2 py-1 text-[13px]" />
            <button onClick={() => setMenu(menu.filter((_, j) => j !== i))}
                    className="rounded border border-[#e0e1ea] px-2 text-[12px] text-red-600">Remove</button>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <button onClick={onSave} disabled={busy}
                className="rounded-lg bg-[#ff5c00] px-5 py-2 text-[13px] font-medium text-white disabled:opacity-50">Save</button>
        {saved && <span className="text-[13px] text-green-600">Saved ✓</span>}
      </div>
    </div>
  )
}
