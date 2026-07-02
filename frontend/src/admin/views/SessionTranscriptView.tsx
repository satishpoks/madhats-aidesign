import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getSessionDetail, type SessionDetail } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'

function Bubble({ role, content, meta }: { role: string; content: string; meta: string }) {
  const isUser = role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${isUser ? 'bg-gray-900 text-white' : 'bg-white border border-gray-200 text-gray-800'}`}>
        <div className="mb-0.5 text-[10px] uppercase tracking-wide opacity-60">{role} · {meta}</div>
        <div className="whitespace-pre-wrap">{content}</div>
      </div>
    </div>
  )
}

export function SessionTranscriptView() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<SessionDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    if (!id) return
    getSessionDetail(id)
      .then((d) => { if (active) { setDetail(d); setError(null) } })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Failed to load session') })
    return () => { active = false }
  }, [id])

  if (error) return <ErrorBanner message={error} />
  if (!detail) return <div className="py-8 text-sm text-gray-500">Loading…</div>

  return (
    <div className="space-y-5 max-w-4xl">
      <button onClick={() => navigate('/admin/sessions')} className="text-sm text-gray-500 hover:underline">
        ← Back to sessions
      </button>

      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Session transcript</h1>
        <StatusBadge status={detail.state ?? '—'} />
        <span className="text-sm text-gray-500">{detail.product ?? '—'}</span>
        <span className="font-mono text-xs text-gray-400">{detail.id}</span>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {/* Transcript */}
        <div className="md:col-span-2 space-y-2 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <h2 className="text-sm font-medium text-gray-700">Conversation ({detail.messages.length})</h2>
          {detail.messages.length === 0 && <p className="text-sm text-gray-500">No messages.</p>}
          {detail.messages.map((m, i) => (
            <Bubble
              key={i}
              role={m.role}
              content={m.content}
              meta={`${m.state_before}→${m.state_after} · ${new Date(m.created_at).toLocaleTimeString()}`}
            />
          ))}
        </div>

        {/* Side panel: collected brief, generations, leads */}
        <div className="space-y-4">
          <section className="rounded-lg border border-gray-200 bg-white p-3">
            <h2 className="mb-2 text-sm font-medium text-gray-700">Collected brief</h2>
            <pre className="whitespace-pre-wrap break-words text-xs text-gray-600">
              {JSON.stringify(detail.collected, null, 2)}
            </pre>
          </section>

          <section className="rounded-lg border border-gray-200 bg-white p-3">
            <h2 className="mb-2 text-sm font-medium text-gray-700">Generations ({detail.generations.length})</h2>
            {detail.generations.length === 0 && <p className="text-xs text-gray-500">None.</p>}
            <div className="space-y-2">
              {detail.generations.map((g) => (
                <div key={g.id} className="flex items-center gap-2 text-xs">
                  {(g.watermarked_url ?? g.image_url) && (
                    <img src={g.watermarked_url ?? g.image_url ?? ''} alt={g.tier} className="h-12 w-12 rounded object-cover border border-gray-200" />
                  )}
                  <div>
                    <div className="font-medium">{g.tier} · <StatusBadge status={g.status} /></div>
                    <div className="text-gray-500">{g.model}{g.latency_ms ? ` · ${g.latency_ms}ms` : ''}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-gray-200 bg-white p-3">
            <h2 className="mb-2 text-sm font-medium text-gray-700">Leads ({detail.leads.length})</h2>
            {detail.leads.length === 0 && <p className="text-xs text-gray-500">None.</p>}
            {detail.leads.map((l) => (
              <div key={l.id} className="text-xs text-gray-700">
                {l.name ?? '—'} · {l.email ?? '—'} {l.email_verified ? '✅' : '✉️ unverified'}
              </div>
            ))}
          </section>
        </div>
      </div>
    </div>
  )
}
