import { useCanvasStore, LINE_SHAPES } from '../../store/canvasStore'
import { WEB_SAFE_FONTS, GOOGLE_FONTS } from '../../lib/fonts'

export function SelectedToolbar() {
  const activeFace = useCanvasStore(s => s.activeFace)
  const faces = useCanvasStore(s => s.faces)
  const selectedId = useCanvasStore(s => s.selectedId)
  const update = useCanvasStore(s => s.updateElement)
  const remove = useCanvasStore(s => s.removeElement)
  const duplicate = useCanvasStore(s => s.duplicate)
  const reorder = useCanvasStore(s => s.reorder)

  const el = faces[activeFace].find(e => e.id === selectedId)
  if (!el) return null

  // --- Universal transform helpers (rotate / move / size) ---
  const NUDGE = 0.02
  const SIZE_FACTOR = 1.1
  const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
  const norm360 = (deg: number) => ((deg % 360) + 360) % 360
  const rotateBy = (delta: number) => update(el.id, { rotation: norm360((el.rotation ?? 0) + delta) })
  const nudge = (dx: number, dy: number) =>
    update(el.id, { x: clamp01((el.x ?? 0) + dx), y: clamp01((el.y ?? 0) + dy) })
  const resize = (factor: number) => {
    if (el.type === 'text') {
      update(el.id, { fontSize: Math.max(8, Math.round((el.fontSize ?? 36) * factor)) })
    } else {
      update(el.id, {
        width: clamp01((el.width ?? 0.2) * factor),
        height: clamp01((el.height ?? 0.2) * factor),
      })
    }
  }
  // Drawings have no width/height (geometry lives in `points`), matching their
  // rotate-only on-canvas Transformer — so size is not offered for them.
  const canResize = el.type !== 'drawing'

  return (
    <div className="flex flex-wrap items-center gap-2 p-3 bg-surface border border-border rounded-xl">
      {el.type === 'text' && (
        <>
          <input value={el.content ?? ''} onChange={e => update(el.id, { content: e.target.value })}
            className="bg-base border border-border rounded px-2 py-1 text-sm text-textPrimary" aria-label="Text content" />
          <select value={el.font ?? 'Arial'} onChange={e => update(el.id, { font: e.target.value })}
            className="bg-base border border-border rounded px-2 py-1 text-sm max-w-[9rem]" aria-label="Font"
            style={{ fontFamily: el.font ?? 'Arial' }}>
            <optgroup label="Standard">
              {WEB_SAFE_FONTS.map(f => (
                <option key={f.family} value={f.family} style={{ fontFamily: f.family }}>{f.label}</option>
              ))}
            </optgroup>
            <optgroup label="Google Fonts">
              {GOOGLE_FONTS.map(f => (
                <option key={f.family} value={f.family} style={{ fontFamily: f.family }}>{f.label}</option>
              ))}
            </optgroup>
          </select>
          <input type="color" value={el.colour ?? '#ffffff'} onChange={e => update(el.id, { colour: e.target.value })}
            className="w-8 h-8 p-0 border-0 bg-transparent" aria-label="Text colour" />
          <label className="flex items-center gap-1 text-xs text-textMuted" title="Font size">
            <span aria-hidden="true">A</span>
            <input type="range" min={12} max={96} value={el.fontSize ?? 36}
              onChange={e => update(el.id, { fontSize: Number(e.target.value) })} aria-label="Font size" />
          </label>
          <label className="flex items-center gap-1 text-xs text-textMuted" title="Curve the text">
            <span aria-hidden="true">Curve</span>
            <input type="range" min={-100} max={100} step={5} value={el.curve ?? 0}
              onChange={e => update(el.id, { curve: Number(e.target.value) })} aria-label="Curve text" />
          </label>
        </>
      )}
      {el.type === 'image' && (
        <label className="flex items-center gap-1.5 text-sm text-textPrimary"
          title="Flag this image so the design team knocks out its background when producing the artwork">
          <input type="checkbox" checked={!!el.removeBg}
            onChange={e => update(el.id, { removeBg: e.target.checked })} />
          Remove background
        </label>
      )}
      {el.type === 'drawing' && (
        <label className="flex items-center gap-1 text-xs text-textMuted" title="Stroke colour">
          <span>Colour</span>
          <input type="color" value={el.stroke ?? '#111827'} onChange={e => update(el.id, { stroke: e.target.value })}
            className="w-8 h-8 p-0 border-0 bg-transparent" aria-label="Stroke colour" />
        </label>
      )}
      {el.type === 'shape' && (LINE_SHAPES.includes(el.shapeKind ?? 'rect') ? (
        <>
          <label className="flex items-center gap-1 text-xs text-textMuted" title="Colour">
            <span>Colour</span>
            <input type="color" value={el.fill ?? '#111827'} onChange={e => update(el.id, { fill: e.target.value })}
              className="w-8 h-8 p-0 border-0 bg-transparent" aria-label="Shape colour" />
          </label>
          <label className="flex items-center gap-1 text-xs text-textMuted" title="Thickness">
            <span>Width</span>
            <input type="range" min={2} max={30} value={el.strokeWidth ?? 6}
              onChange={e => update(el.id, { strokeWidth: Number(e.target.value) })} aria-label="Line thickness" />
          </label>
        </>
      ) : (
        <>
          <label className="flex items-center gap-1 text-xs text-textMuted" title="Fill colour">
            <span>Fill</span>
            <input type="color" value={el.fill ?? '#2563eb'} onChange={e => update(el.id, { fill: e.target.value, filled: true })}
              className="w-8 h-8 p-0 border-0 bg-transparent" aria-label="Fill colour" />
          </label>
          <label className="flex items-center gap-1 text-xs text-textMuted" title="Border colour">
            <span>Border</span>
            <input type="color" value={el.stroke ?? '#111827'} onChange={e => update(el.id, { stroke: e.target.value })}
              className="w-8 h-8 p-0 border-0 bg-transparent" aria-label="Border colour" />
          </label>
          <label className="flex items-center gap-1 text-xs text-textMuted" title="Border width">
            <span>W</span>
            <input type="range" min={0} max={24} value={el.strokeWidth ?? 0}
              onChange={e => update(el.id, { strokeWidth: Number(e.target.value) })} aria-label="Border width" />
          </label>
          <button
            onClick={() => update(el.id, el.filled === false
              ? { filled: true }
              : { filled: false, strokeWidth: Math.max(el.strokeWidth ?? 0, 4) })}
            className="px-2 py-1 text-xs border border-border rounded"
            title="Toggle filled / outline"
          >
            {el.filled === false ? 'Outline' : 'Filled'}
          </button>
        </>
      ))}
      {/* Universal transform block — rotate / move / (size) for every element. */}
      <div className="flex items-center gap-1" role="group" aria-label="Rotate">
        <button onClick={() => rotateBy(-45)} className="px-2 py-1 text-sm border border-border rounded" title="Rotate 45° left" aria-label="Rotate left 45 degrees">⟲</button>
        <input type="number" value={Math.round(el.rotation ?? 0)} onChange={e => update(el.id, { rotation: norm360(Number(e.target.value) || 0) })}
          className="w-14 bg-base border border-border rounded px-1 py-1 text-sm text-textPrimary" aria-label="Rotation degrees" title="Rotation (degrees)" />
        <button onClick={() => rotateBy(45)} className="px-2 py-1 text-sm border border-border rounded" title="Rotate 45° right" aria-label="Rotate right 45 degrees">⟳</button>
        <button onClick={() => update(el.id, { rotation: 0 })} className="px-2 py-1 text-xs border border-border rounded" title="Reset rotation" aria-label="Reset rotation">Reset</button>
      </div>
      <div className="flex items-center gap-1" role="group" aria-label="Move">
        <button onClick={() => nudge(0, -NUDGE)} className="px-2 py-1 text-sm border border-border rounded" title="Move up" aria-label="Nudge up">↑</button>
        <button onClick={() => nudge(0, NUDGE)} className="px-2 py-1 text-sm border border-border rounded" title="Move down" aria-label="Nudge down">↓</button>
        <button onClick={() => nudge(-NUDGE, 0)} className="px-2 py-1 text-sm border border-border rounded" title="Move left" aria-label="Nudge left">←</button>
        <button onClick={() => nudge(NUDGE, 0)} className="px-2 py-1 text-sm border border-border rounded" title="Move right" aria-label="Nudge right">→</button>
      </div>
      {canResize && (
        <div className="flex items-center gap-1" role="group" aria-label="Size">
          <button onClick={() => resize(1 / SIZE_FACTOR)} className="px-2 py-1 text-sm border border-border rounded" title="Smaller" aria-label="Decrease size">−</button>
          <button onClick={() => resize(SIZE_FACTOR)} className="px-2 py-1 text-sm border border-border rounded" title="Larger" aria-label="Increase size">+</button>
        </div>
      )}
      <button onClick={() => reorder(el.id, 'up')} className="px-2 py-1 text-sm border border-border rounded" title="Bring forward">↑</button>
      <button onClick={() => reorder(el.id, 'down')} className="px-2 py-1 text-sm border border-border rounded" title="Send back">↓</button>
      <button onClick={() => duplicate(el.id)} className="px-2 py-1 text-sm border border-border rounded" title="Duplicate">Duplicate</button>
      <button onClick={() => remove(el.id)} className="px-2 py-1 text-sm text-red-600 border border-red-200 rounded" title="Delete">Delete</button>
    </div>
  )
}
