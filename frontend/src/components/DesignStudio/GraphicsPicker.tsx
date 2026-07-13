import { useEffect, useState } from 'react'
import { Stage, Layer, Group } from 'react-konva'
import { Modal } from '../Modal'
import { listGraphics } from '../../lib/api'
import type { Graphic } from '../../lib/types'
import { type CanvasElement, type ShapeKind, LINE_SHAPES } from '../../store/canvasStore'
import { ShapePrimitive } from './nodes'

const TABS: { key: 'clipart' | 'company'; label: string }[] = [
  { key: 'clipart', label: 'Clipart' },
  { key: 'company', label: 'Company' },
]

// The built-in, recolourable shape palette (the "Clipart" section).
const SHAPES: { kind: ShapeKind; label: string }[] = [
  { kind: 'rect', label: 'Rectangle' },
  { kind: 'square', label: 'Square' },
  { kind: 'roundedRect', label: 'Rounded' },
  { kind: 'circle', label: 'Circle' },
  { kind: 'ellipse', label: 'Oval' },
  { kind: 'triangle', label: 'Triangle' },
  { kind: 'diamond', label: 'Diamond' },
  { kind: 'pentagon', label: 'Pentagon' },
  { kind: 'hexagon', label: 'Hexagon' },
  { kind: 'star', label: 'Star' },
  { kind: 'line', label: 'Line' },
  { kind: 'arrow', label: 'Arrow' },
  { kind: 'doubleArrow', label: 'Double arrow' },
]

const T = 46

/** Tiny Konva preview of a shape kind (matches how it renders on the canvas). */
function ShapeThumb({ kind }: { kind: ShapeKind }) {
  const el: CanvasElement = {
    id: 't', type: 'shape', shapeKind: kind, x: 0, y: 0, width: 1, height: 1, rotation: 0, zIndex: 0,
    fill: '#2563eb', stroke: '#111827', strokeWidth: 0, filled: true,
  }
  const line = LINE_SHAPES.includes(kind)
  const lw = T * 0.82
  const lh = line ? T * 0.3 : T * 0.82
  return (
    <Stage width={T} height={T} listening={false} style={{ pointerEvents: 'none' }}>
      <Layer>
        <Group x={(T - lw) / 2} y={(T - lh) / 2}>
          <ShapePrimitive el={el} lw={lw} lh={lh} listening={false} />
        </Group>
      </Layer>
    </Stage>
  )
}

interface GraphicsPickerProps {
  open: boolean
  onClose: () => void
  onPickShape: (kind: ShapeKind) => void
  onPickImage: (url: string) => void
}

export function GraphicsPicker({ open, onClose, onPickShape, onPickImage }: GraphicsPickerProps) {
  const [tab, setTab] = useState<'clipart' | 'company'>('clipart')
  const [items, setItems] = useState<Graphic[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || tab !== 'company') return
    let cancelled = false
    setLoading(true); setError(null)
    listGraphics('company').then(
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

        {tab === 'clipart' && (
          <div className="grid grid-cols-4 gap-2 max-h-72 overflow-y-auto">
            {SHAPES.map(s => (
              <button
                key={s.kind}
                onClick={() => { onPickShape(s.kind); onClose() }}
                title={s.label}
                aria-label={`Add ${s.label}`}
                className="flex flex-col items-center gap-0.5 rounded-lg border border-border bg-surface p-1.5 hover:border-accent transition-colors"
              >
                <ShapeThumb kind={s.kind} />
                <span className="text-[9px] text-textMuted">{s.label}</span>
              </button>
            ))}
          </div>
        )}

        {tab === 'company' && (
          <>
            {loading && <p className="text-sm text-textMuted py-6 text-center">Loading…</p>}
            {error && <p className="text-sm text-red-600 py-4 text-center">{error}</p>}
            {!loading && !error && items.length === 0 && (
              <p className="text-sm text-textMuted py-6 text-center">No company graphics yet.</p>
            )}
            {!loading && !error && items.length > 0 && (
              <div className="grid grid-cols-4 gap-2 max-h-72 overflow-y-auto">
                {items.map(g => (
                  <button
                    key={g.id}
                    onClick={() => { onPickImage(g.url); onClose() }}
                    title={g.name}
                    aria-label={`Add ${g.name}`}
                    className="aspect-square rounded-lg border border-border bg-surface p-1.5 hover:border-accent transition-colors"
                  >
                    <img src={g.url} alt={g.name} crossOrigin="anonymous" className="w-full h-full object-contain" draggable={false} />
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  )
}
