import { useEffect, useState } from 'react'
import { Modal } from '../Modal'
import { listGraphics } from '../../lib/api'
import type { Graphic } from '../../lib/types'

const TABS: { key: 'clipart' | 'company'; label: string }[] = [
  { key: 'clipart', label: 'Clipart' },
  { key: 'company', label: 'Company' },
]

interface GraphicsPickerProps {
  open: boolean
  onClose: () => void
  /** Called with the graphic's /media URL when one is picked. */
  onPick: (url: string) => void
}

export function GraphicsPicker({ open, onClose, onPick }: GraphicsPickerProps) {
  const [tab, setTab] = useState<'clipart' | 'company'>('clipart')
  const [items, setItems] = useState<Graphic[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true); setError(null)
    listGraphics(tab).then(
      g => { if (!cancelled) setItems(g) },
      () => { if (!cancelled) setError('Could not load graphics') },
    ).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [open, tab])

  return (
    <Modal open={open} title="Add a graphic" onClose={onClose}>
      <div className="flex flex-col gap-3 p-2 w-[22rem] max-w-full">
        <div className="flex gap-2">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-1 rounded-full text-xs transition-colors ${
                tab === t.key ? 'bg-accent text-white' : 'bg-surface border border-border text-textMuted hover:border-accent'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {loading && <p className="text-sm text-textMuted py-6 text-center">Loading…</p>}
        {error && <p className="text-sm text-red-600 py-4 text-center">{error}</p>}
        {!loading && !error && items.length === 0 && (
          <p className="text-sm text-textMuted py-6 text-center">No {tab} graphics yet.</p>
        )}

        {!loading && !error && items.length > 0 && (
          <div className="grid grid-cols-4 gap-2 max-h-72 overflow-y-auto">
            {items.map(g => (
              <button
                key={g.id}
                onClick={() => { onPick(g.url); onClose() }}
                title={g.name}
                aria-label={`Add ${g.name}`}
                className="aspect-square rounded-lg border border-border bg-surface p-1.5 hover:border-accent transition-colors"
              >
                <img src={g.url} alt={g.name} crossOrigin="anonymous" className="w-full h-full object-contain" draggable={false} />
              </button>
            ))}
          </div>
        )}
      </div>
    </Modal>
  )
}
