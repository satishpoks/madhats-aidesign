import { useCanvasStore } from '../../store/canvasStore'

const FONTS = ['Arial', 'Impact', 'Georgia', 'Courier New', 'Verdana']

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
            className="bg-base border border-border rounded px-2 py-1 text-sm" aria-label="Font">
            {FONTS.map(f => <option key={f} value={f}>{f}</option>)}
          </select>
          <input type="color" value={el.colour ?? '#ffffff'} onChange={e => update(el.id, { colour: e.target.value })}
            className="w-8 h-8 p-0 border-0 bg-transparent" aria-label="Text colour" />
          <input type="range" min={12} max={96} value={el.fontSize ?? 36}
            onChange={e => update(el.id, { fontSize: Number(e.target.value) })} aria-label="Font size" />
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
