import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { listSubmissions, updateSubmission, type Submission } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'

export function SubmissionDetailView() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [sub, setSub] = useState<Submission | null>(null)
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    // No single-submission GET exists; fetch the list and pick the row.
    listSubmissions()
      .then((data) => {
        if (!active) return
        const found = data.find((s) => s.id === id) ?? null
        setSub(found)
        setNotes(found?.reviewer_notes ?? '')
        setError(found ? null : 'Submission not found')
      })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Failed to load') })
    return () => { active = false }
  }, [id])

  async function decide(status: 'approved' | 'rejected') {
    if (!id) return
    setBusy(true)
    setError(null)
    try {
      await updateSubmission(id, { review_status: status, reviewer_notes: notes })
      navigate('/admin/submissions')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Update failed')
    } finally {
      setBusy(false)
    }
  }

  if (error && !sub) return <ErrorBanner message={error} />
  if (!sub) return <div className="py-8 text-sm text-gray-500">Loading…</div>

  const customer = sub.customer as { name?: string; email?: string } | null

  return (
    <div className="space-y-4 max-w-3xl">
      <button onClick={() => navigate('/admin/submissions')} className="text-sm text-gray-500 hover:underline">
        ← Back to queue
      </button>
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Submission</h1>
        <StatusBadge status={sub.review_status} />
      </div>
      {error && <ErrorBanner message={error} />}

      <div className="grid grid-cols-2 gap-4 text-sm">
        <div><span className="text-gray-500">Session:</span> {sub.session_id}</div>
        <div><span className="text-gray-500">Customer:</span> {customer?.name ?? '—'}</div>
      </div>

      <div className="flex flex-wrap gap-3">
        {sub.final_image_urls.map((url) => (
          <img key={url} src={url} alt="concept" className="w-48 rounded border border-gray-200" />
        ))}
      </div>

      <label className="block text-sm font-medium text-gray-700">
        Reviewer notes
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
        />
      </label>

      <div className="flex gap-2">
        <button
          onClick={() => decide('approved')}
          disabled={busy}
          className="rounded bg-green-600 text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          Approve
        </button>
        <button
          onClick={() => decide('rejected')}
          disabled={busy}
          className="rounded bg-red-600 text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          Reject
        </button>
      </div>
    </div>
  )
}
