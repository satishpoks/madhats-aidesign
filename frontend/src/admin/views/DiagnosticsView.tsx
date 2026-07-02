import { useEffect, useState } from 'react'
import {
  getDiagnostics,
  listGenerationLogs,
  type Diagnostics,
  type GenerationLog,
} from '../adminApi'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { ErrorBanner } from '../components/ErrorBanner'

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3">
      <div className="text-2xl font-semibold text-gray-900">{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  )
}

function Flag({ label, on }: { label: string; on: boolean }) {
  return (
    <div className="flex items-center justify-between rounded border border-gray-200 bg-white px-3 py-1.5 text-sm">
      <span className="text-gray-700">{label}</span>
      <span className={on ? 'text-green-600' : 'text-gray-400'}>{on ? '● on' : '○ off'}</span>
    </div>
  )
}

export function DiagnosticsView() {
  const [diag, setDiag] = useState<Diagnostics | null>(null)
  const [logs, setLogs] = useState<GenerationLog[]>([])
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<GenerationLog | null>(null)

  useEffect(() => {
    let active = true
    Promise.all([getDiagnostics(), listGenerationLogs(100, 0)])
      .then(([d, l]) => { if (active) { setDiag(d); setLogs(l.items); setError(null) } })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Failed to load diagnostics') })
    return () => { active = false }
  }, [])

  const logColumns: Column<GenerationLog>[] = [
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'tier', header: 'Tier', render: (r) => r.tier ?? '—' },
    { key: 'model', header: 'Model', render: (r) => r.model ?? '—' },
    { key: 'attempt', header: 'Attempt', render: (r) => r.attempt },
    { key: 'latency', header: 'Latency', render: (r) => (r.latency_ms ? `${r.latency_ms}ms` : '—') },
    { key: 'error', header: 'Error', render: (r) => (r.error ? <span className="text-red-600">{r.error.slice(0, 40)}</span> : '—') },
    { key: 'when', header: 'When', render: (r) => new Date(r.request_at).toLocaleString() },
  ]

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Diagnostics</h1>
      {error && <ErrorBanner message={error} />}

      {diag && (
        <>
          <section className="space-y-2">
            <h2 className="text-sm font-medium text-gray-700">Counts</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
              <Stat label="Stores" value={diag.counts.stores} />
              <Stat label="Sessions" value={diag.counts.sessions} />
              <Stat label="Generations" value={diag.counts.generations} />
              <Stat label="Gen. failed" value={diag.counts.generations_failed} />
              <Stat label="Leads" value={diag.counts.leads} />
              <Stat label="Leads verified" value={diag.counts.leads_verified} />
              <Stat label="Pending review" value={diag.counts.submissions_pending} />
            </div>
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-medium text-gray-700">
              Environment: <span className="font-mono">{diag.app_env}</span>
            </h2>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <Flag label="Gemini key" on={diag.providers.gemini_api_key_set} />
              <Flag label="Anthropic key" on={diag.providers.anthropic_api_key_set} />
              <Flag label="Resend key" on={diag.providers.resend_api_key_set} />
              <Flag label="Sentry" on={diag.providers.sentry_enabled} />
            </div>
            <div className="grid gap-2 text-sm text-gray-600 sm:grid-cols-2">
              <div>Preview provider: <span className="font-mono">{diag.providers.image_provider_preview}</span> ({diag.providers.gemini_preview_model})</div>
              <div>Final provider: <span className="font-mono">{diag.providers.image_provider_final}</span> ({diag.providers.gemini_final_model})</div>
              <div>Conversation model: <span className="font-mono">{diag.providers.claude_haiku_model}</span></div>
            </div>
          </section>
        </>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-gray-700">Generation audit log (latest 100)</h2>
        <DataTable<GenerationLog>
          columns={logColumns}
          rows={logs}
          empty="No generation logs"
          onRowClick={(r) => setSelected(r)}
        />
      </section>

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setSelected(null)}>
          <div className="max-h-[85vh] w-full max-w-3xl overflow-auto rounded-lg bg-white p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">Generation log · {selected.status}</h3>
              <button onClick={() => setSelected(null)} className="text-sm text-gray-500 hover:underline">Close</button>
            </div>
            <div className="text-sm text-gray-600">
              {selected.tier} · {selected.model ?? 'unknown model'} · attempt {selected.attempt}
              {selected.latency_ms ? ` · ${selected.latency_ms}ms` : ''}
            </div>
            {selected.error && <ErrorBanner message={selected.error} />}
            <div>
              <div className="mb-1 text-xs font-medium text-gray-500">Prompt</div>
              <pre className="whitespace-pre-wrap rounded bg-gray-900 p-3 text-xs text-gray-100">{selected.full_prompt}</pre>
            </div>
            {selected.params && (
              <div>
                <div className="mb-1 text-xs font-medium text-gray-500">Params</div>
                <pre className="whitespace-pre-wrap rounded bg-gray-50 border border-gray-200 p-3 text-xs">{JSON.stringify(selected.params, null, 2)}</pre>
              </div>
            )}
            {(selected.reference_image_url || selected.output_image_url) && (
              <div className="flex gap-3">
                {selected.reference_image_url && (
                  <div>
                    <div className="mb-1 text-xs text-gray-500">Reference</div>
                    <img src={selected.reference_image_url} alt="reference" className="w-40 rounded border border-gray-200" />
                  </div>
                )}
                {selected.output_image_url && (
                  <div>
                    <div className="mb-1 text-xs text-gray-500">Output</div>
                    <img src={selected.output_image_url} alt="output" className="w-40 rounded border border-gray-200" />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
