import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getSessionDetail, type SessionDetail } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'

const ANGLES = ['front', 'back', 'left', 'right'] as const

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-gray-400">{label}</div>
      <div className="text-sm text-gray-800">{value || '—'}</div>
    </div>
  )
}

/** Render the collected brief as labelled fields, falling back to raw JSON. */
function Brief({ collected }: { collected: Record<string, unknown> }) {
  const keys = Object.keys(collected)
  if (keys.length === 0) return <p className="text-sm text-gray-500">No brief captured yet.</p>
  return (
    <div className="grid grid-cols-2 gap-3">
      {keys.map((k) => {
        const v = collected[k]
        const text = typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v)
        return <Field key={k} label={k.replace(/_/g, ' ')} value={text} />
      })}
    </div>
  )
}

export function LeadDetailView() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showTranscript, setShowTranscript] = useState(false)

  useEffect(() => {
    let active = true
    if (!id) return
    getSessionDetail(id)
      .then((d) => { if (active) { setDetail(d); setError(null) } })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Failed to load lead') })
    return () => { active = false }
  }, [id])

  if (error) return <ErrorBanner message={error} />
  if (!detail) return <div className="py-8 text-sm text-gray-500">Loading…</div>

  const lead = detail.leads[0]
  // 360° angles: prefer named view_images, fall back to the front reference.
  const angleImages = ANGLES
    .map((a) => ({ angle: a, url: detail.view_images[a] }))
    .filter((x) => x.url)
  const capImages = angleImages.length > 0
    ? angleImages
    : detail.reference_image_url
      ? [{ angle: 'front', url: detail.reference_image_url }]
      : []
  const generated = detail.generations.filter((g) => g.watermarked_url || g.image_url)

  return (
    <div className="space-y-6 max-w-5xl">
      <button onClick={() => navigate('/admin/leads')} className="text-sm text-gray-500 hover:underline">
        ← Back to leads
      </button>

      {/* Header: who + status */}
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{lead?.name || lead?.email || 'Anonymous visitor'}</h1>
        <StatusBadge status={detail.state ?? '—'} />
        <span className="font-mono text-xs text-gray-400">{detail.id}</span>
      </div>

      {/* Contact */}
      <section className="grid grid-cols-2 gap-3 rounded-lg border border-gray-200 bg-white p-4 sm:grid-cols-4">
        <Field label="Name" value={lead?.name} />
        <Field label="Email" value={lead ? <>{lead.email} {lead.email_verified ? '✅' : '✉️ unverified'}</> : '—'} />
        <Field label="Phone" value={lead?.phone} />
        <Field label="Created" value={detail.created_at ? new Date(detail.created_at).toLocaleString() : '—'} />
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Selected cap — 360° */}
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-gray-700">Selected cap — {detail.product ?? 'unknown'}</h2>
          {capImages.length === 0 ? (
            <p className="text-sm text-gray-500">No product image.</p>
          ) : (
            <div className="flex flex-wrap gap-3">
              {capImages.map(({ angle, url }) => (
                <figure key={angle} className="text-center">
                  <img src={url} alt={angle} className="h-32 w-32 rounded-lg object-cover border border-gray-200" />
                  <figcaption className="mt-1 text-[11px] capitalize text-gray-500">{angle}</figcaption>
                </figure>
              ))}
            </div>
          )}
        </section>

        {/* Design brief */}
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-gray-700">What the customer wants</h2>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <Brief collected={detail.collected} />
          </div>
        </section>
      </div>

      {/* Generated images */}
      <section className="space-y-2">
        <h2 className="text-sm font-medium text-gray-700">AI-generated mockups ({generated.length})</h2>
        {generated.length === 0 ? (
          <p className="text-sm text-gray-500">No images generated for this lead.</p>
        ) : (
          <div className="flex flex-wrap gap-4">
            {generated.map((g) => (
              <figure key={g.id} className="text-center">
                <img
                  src={g.watermarked_url ?? g.image_url ?? ''}
                  alt={g.tier}
                  className="h-48 w-48 rounded-lg object-cover border border-gray-200"
                />
                <figcaption className="mt-1 text-[11px] text-gray-500">
                  {g.tier} · <StatusBadge status={g.status} />
                </figcaption>
              </figure>
            ))}
          </div>
        )}
      </section>

      {/* Transcript (collapsible) */}
      <section className="space-y-2">
        <button
          onClick={() => setShowTranscript((v) => !v)}
          className="text-sm font-medium text-gray-700 hover:underline"
        >
          {showTranscript ? '▾' : '▸'} Conversation transcript ({detail.messages.length})
        </button>
        {showTranscript && (
          <div className="space-y-2 rounded-lg border border-gray-200 bg-gray-50 p-4">
            {detail.messages.length === 0 && <p className="text-sm text-gray-500">No messages.</p>}
            {detail.messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${m.role === 'user' ? 'bg-gray-900 text-white' : 'bg-white border border-gray-200 text-gray-800'}`}>
                  <div className="mb-0.5 text-[10px] uppercase tracking-wide opacity-60">
                    {m.role} · {m.state_before}→{m.state_after}
                  </div>
                  <div className="whitespace-pre-wrap">{m.content}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
