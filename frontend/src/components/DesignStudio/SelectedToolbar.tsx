import { useState } from 'react'
import { useCanvasStore, LINE_SHAPES, type CanvasElement } from '../../store/canvasStore'
import { useSessionStore } from '../../store/sessionStore'
import { WEB_SAFE_FONTS, GOOGLE_FONTS } from '../../lib/fonts'
import { toggleBackground } from '../../lib/bgRemove'

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
      {el.type === 'image' && <BgRemoveToggle el={el} />}
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
      <button onClick={() => reorder(el.id, 'up')} className="px-2 py-1 text-sm border border-border rounded" title="Bring forward">↑</button>
      <button onClick={() => reorder(el.id, 'down')} className="px-2 py-1 text-sm border border-border rounded" title="Send back">↓</button>
      <button onClick={() => duplicate(el.id)} className="px-2 py-1 text-sm border border-border rounded" title="Duplicate">Duplicate</button>
      <button onClick={() => remove(el.id)} className="px-2 py-1 text-sm text-red-600 border border-red-200 rounded" title="Delete">Delete</button>
    </div>
  )
}

/** Background-removal toggle: runs client-side matting, swaps the element's image
 *  to the transparent (or restored original) upload. Async, with a busy state. */
function BgRemoveToggle({ el }: { el: CanvasElement }) {
  const sessionId = useSessionStore(s => s.sessionId)
  const update = useCanvasStore(s => s.updateElement)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function onToggle(on: boolean) {
    if (!sessionId) return
    setBusy(true); setFailed(false)
    try {
      const patch = await toggleBackground(sessionId, el, on)
      update(el.id, patch)
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <label className="flex items-center gap-1.5 text-sm text-textPrimary">
      <input type="checkbox" checked={!!el.removeBg} disabled={busy}
        onChange={e => void onToggle(e.target.checked)} />
      {busy ? 'Removing…' : failed ? 'Failed — try again' : 'Remove background'}
    </label>
  )
}
