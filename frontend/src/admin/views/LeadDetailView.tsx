import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getSessionDetail, type SessionDetail, type SessionGeneration } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'

const ANGLES = ['front', 'side', 'back', 'left', 'right'] as const

// Curated, human-friendly brief fields (in display order). Everything else is
// internal plumbing (ids, hashes, flags) and stays in the collapsible raw view.
const BRIEF_FIELDS: { key: string; label: string }[] = [
  { key: 'purpose', label: 'Purpose' },
  { key: 'decoration_type', label: 'Decoration' },
  { key: 'placement_zone', label: 'Placement' },
  { key: 'placement_position', label: 'Position' },
  { key: 'quantity', label: 'Quantity' },
  { key: 'has_logo', label: 'Has logo' },
  { key: 'wants_pins', label: 'Wants pins' },
  { key: 'youth_flag', label: 'Youth sizing' },
  { key: 'remove_bg', label: 'Remove background' },
]

function fmt(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function Avatar({ name }: { name: string }) {
  return (
    <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-[#fff2ea] text-[18px] font-semibold text-[#bf2e00]">
      {(name[0] ?? '?').toUpperCase()}
    </span>
  )
}

function Card({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-[#e0e1ea] bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[13px] font-semibold text-[#1a1a2e]">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

export function LeadDetailView() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showTranscript, setShowTranscript] = useState(false)
  const [showRaw, setShowRaw] = useState(false)
  const [activeGen, setActiveGen] = useState(0)

  useEffect(() => {
    let active = true
    if (!id) return
    getSessionDetail(id)
      .then((d) => { if (active) { setDetail(d); setError(null); setActiveGen(0) } })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Failed to load lead') })
    return () => { active = false }
  }, [id])

  const capImages = useMemo(() => {
    if (!detail) return []
    const named = ANGLES.map((a) => ({ angle: a, url: detail.view_images[a] })).filter((x) => x.url)
    if (named.length > 0) return named as { angle: string; url: string }[]
    return detail.reference_image_url ? [{ angle: 'front', url: detail.reference_image_url }] : []
  }, [detail])

  const generated = useMemo(
    () => (detail?.generations ?? []).filter((g) => g.watermarked_url || g.image_url),
    [detail],
  )

  if (error) return <ErrorBanner message={error} />
  if (!detail) return <div className="py-10 text-center text-sm text-[#6b6b80]">Loading…</div>

  const lead = detail.leads[0]
  const displayName = lead?.name || lead?.email || 'Anonymous visitor'
  const briefRows = BRIEF_FIELDS.filter((f) => detail.collected[f.key] !== undefined)
  const pinCount = Array.isArray(detail.collected.pin_annotations)
    ? (detail.collected.pin_annotations as unknown[]).length
    : 0
  const active: SessionGeneration | undefined = generated[activeGen]

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <button onClick={() => navigate('/admin/leads')} className="text-sm text-[#6b6b80] hover:text-[#1a1a2e]">
        ← Back to leads
      </button>

      {/* Hero */}
      <div className="flex flex-wrap items-center gap-4 rounded-xl border border-[#e0e1ea] bg-white p-5">
        <Avatar name={displayName} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-[20px] font-semibold text-[#1a1a2e]">{displayName}</h1>
            <StatusBadge status={detail.state ?? '—'} />
          </div>
          <div className="mt-0.5 text-[13px] text-[#6b6b80]">
            {lead?.email ?? 'no email captured'}
            {lead?.email_verified ? ' · ✅ verified' : lead?.email ? ' · unverified' : ''}
            {lead?.phone ? ` · ${lead.phone}` : ''}
          </div>
        </div>
        <div className="text-right text-[12px] text-[#6b6b80]">
          <div className="font-medium text-[#1a1a2e]">{detail.product ?? 'No product'}</div>
          <div>{detail.channel ?? 'web'} · {detail.created_at ? new Date(detail.created_at).toLocaleString() : '—'}</div>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        {/* Left: the visual story */}
        <div className="space-y-5 lg:col-span-2">
          <Card title={`AI-generated mockups (${generated.length})`}>
            {generated.length === 0 ? (
              <div className="flex h-56 items-center justify-center rounded-lg bg-[#f8f9fa] text-sm text-[#6b6b80]">
                No images generated for this lead yet.
              </div>
            ) : (
              <div className="space-y-3">
                <div className="relative overflow-hidden rounded-lg border border-[#e0e1ea] bg-[#f8f9fa]">
                  <img
                    src={active?.watermarked_url ?? active?.image_url ?? ''}
                    alt="mockup"
                    className="mx-auto max-h-[420px] w-full object-contain"
                  />
                  {active && (
                    <div className="absolute left-3 top-3 flex items-center gap-2">
                      <span className="rounded-full bg-white/90 px-2 py-0.5 text-[11px] font-medium text-[#1a1a2e]">{active.tier}</span>
                      <StatusBadge status={active.status} />
                    </div>
                  )}
                </div>
                {generated.length > 1 && (
                  <div className="flex flex-wrap gap-2">
                    {generated.map((g, i) => (
                      <button
                        key={g.id}
                        onClick={() => setActiveGen(i)}
                        className={`overflow-hidden rounded-lg border-2 transition-colors ${i === activeGen ? 'border-[#ff5c00]' : 'border-[#e0e1ea] hover:border-[#c9cad4]'}`}
                      >
                        <img src={g.watermarked_url ?? g.image_url ?? ''} alt={g.tier} className="h-16 w-16 object-cover" />
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </Card>

          <Card title="Selected cap — 360°" action={<span className="text-[12px] text-[#6b6b80]">{detail.product ?? ''}</span>}>
            {capImages.length === 0 ? (
              <p className="text-sm text-[#6b6b80]">No product image.</p>
            ) : (
              <div className="flex flex-wrap gap-3">
                {capImages.map(({ angle, url }) => (
                  <figure key={angle} className="text-center">
                    <img src={url} alt={angle} className="size-28 rounded-lg border border-[#e0e1ea] bg-[#f8f9fa] object-cover" />
                    <figcaption className="mt-1 text-[11px] capitalize text-[#6b6b80]">{angle}</figcaption>
                  </figure>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Right: what they want */}
        <div className="space-y-5">
          <Card title="What the customer wants">
            {briefRows.length === 0 ? (
              <p className="text-sm text-[#6b6b80]">No brief captured yet.</p>
            ) : (
              <dl className="divide-y divide-[#f0f1f5]">
                {briefRows.map((f) => (
                  <div key={f.key} className="flex items-center justify-between py-2">
                    <dt className="text-[12px] text-[#6b6b80]">{f.label}</dt>
                    <dd className="text-[13px] font-medium text-[#1a1a2e]">{fmt(detail.collected[f.key])}</dd>
                  </div>
                ))}
                {pinCount > 0 && (
                  <div className="flex items-center justify-between py-2">
                    <dt className="text-[12px] text-[#6b6b80]">Placement pins</dt>
                    <dd className="text-[13px] font-medium text-[#1a1a2e]">{pinCount}</dd>
                  </div>
                )}
              </dl>
            )}
            <button
              onClick={() => setShowRaw((v) => !v)}
              className="mt-3 text-[12px] font-medium text-[#ff5c00] hover:underline"
            >
              {showRaw ? 'Hide' : 'Show'} all captured data
            </button>
            {showRaw && (
              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-[#f8f9fa] p-3 text-[11px] text-[#6b6b80]">
                {JSON.stringify(detail.collected, null, 2)}
              </pre>
            )}
          </Card>

          <Card title="Lead">
            <dl className="space-y-2 text-[13px]">
              <div className="flex justify-between"><dt className="text-[#6b6b80]">Name</dt><dd className="font-medium text-[#1a1a2e]">{lead?.name ?? '—'}</dd></div>
              <div className="flex justify-between gap-3"><dt className="text-[#6b6b80]">Email</dt><dd className="truncate font-medium text-[#1a1a2e]">{lead?.email ?? '—'}</dd></div>
              <div className="flex justify-between"><dt className="text-[#6b6b80]">Phone</dt><dd className="font-medium text-[#1a1a2e]">{lead?.phone ?? '—'}</dd></div>
              <div className="flex justify-between"><dt className="text-[#6b6b80]">Verified</dt><dd className="font-medium text-[#1a1a2e]">{lead?.email_verified ? 'Yes' : 'No'}</dd></div>
            </dl>
          </Card>
        </div>
      </div>

      {/* Transcript */}
      <Card
        title={`Conversation transcript (${detail.messages.length})`}
        action={
          <button onClick={() => setShowTranscript((v) => !v)} className="text-[12px] font-medium text-[#ff5c00] hover:underline">
            {showTranscript ? 'Hide' : 'Show'}
          </button>
        }
      >
        {!showTranscript ? (
          <p className="text-[13px] text-[#6b6b80]">{detail.messages.length} messages — click Show to expand.</p>
        ) : detail.messages.length === 0 ? (
          <p className="text-sm text-[#6b6b80]">No messages.</p>
        ) : (
          <div className="space-y-2">
            {detail.messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[75%] rounded-2xl px-3 py-2 text-sm ${m.role === 'user' ? 'bg-[#ff5c00] text-white' : 'border border-[#e0e1ea] bg-[#f8f9fa] text-[#1a1a2e]'}`}>
                  <div className="mb-0.5 text-[10px] uppercase tracking-wide opacity-60">
                    {m.role} · {m.state_before}→{m.state_after}
                  </div>
                  <div className="whitespace-pre-wrap">{m.content}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
