import { useCanvasStore } from '../../store/canvasStore'
import { WEB_SAFE_FONTS, GOOGLE_FONTS } from '../../lib/fonts'

export function SelectedToolbar() {
  const activeFace = useCanvasStore(s => s.activeFace)
  const faces = useCanvasStore(s => s.faces)
  const selectedId = useCanvasStore(s => s.selectedId)
  const update = useCanvasStore(s => s.updateElement)
  const remove = useCanvasStore(s => s.removeElement)
  const reorder = useCanvasStore(s => s.reorder)

  const el = faces[activeFace].find(e => e.id === selectedId)
  if (!el) return null

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
        <label className="flex items-center gap-1.5 text-sm text-textPrimary">
          <input type="checkbox" checked={!!el.removeBg} onChange={e => update(el.id, { removeBg: e.target.checked })} />
          Remove background
        </label>
      )}
      <button onClick={() => reorder(el.id, 'up')} className="px-2 py-1 text-sm border border-border rounded" title="Bring forward">↑</button>
      <button onClick={() => reorder(el.id, 'down')} className="px-2 py-1 text-sm border border-border rounded" title="Send back">↓</button>
      <button onClick={() => remove(el.id)} className="px-2 py-1 text-sm text-red-600 border border-red-200 rounded" title="Delete">Delete</button>
    </div>
  )
}
