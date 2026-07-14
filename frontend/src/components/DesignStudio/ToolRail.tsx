import type { Colourway } from '../../store/canvasStore'
import { useCanvasStore } from '../../store/canvasStore'

interface ToolRailProps {
  onAddText: () => void
  onUploadClick: () => void
  onGraphicsClick: () => void
  colourways: Colourway[]
  onRender: () => void
  rendering: boolean
  rendered: boolean
  /** Canvas is view-only (chat not at canvas_design) — disable every tool so
   *  no modification can be made, without blurring the panel. */
  locked?: boolean
}

export function ToolRail({ onAddText, onUploadClick, onGraphicsClick, colourways, onRender, rendering, rendered, locked }: ToolRailProps) {
  const colourway = useCanvasStore(s => s.colourway)
  const setColourway = useCanvasStore(s => s.setColourway)
  const drawMode = useCanvasStore(s => s.drawMode)
  const setDrawMode = useCanvasStore(s => s.setDrawMode)
  const drawColour = useCanvasStore(s => s.drawColour)
  const setDrawColour = useCanvasStore(s => s.setDrawColour)
  const drawWidth = useCanvasStore(s => s.drawWidth)
  const setDrawWidth = useCanvasStore(s => s.setDrawWidth)
  return (
    <div className="flex flex-col gap-3 p-4 w-full md:w-64">
      <button onClick={onAddText} disabled={locked} className="px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border">+ Add text</button>
      <button onClick={onUploadClick} disabled={locked} className="px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border">↑ Upload image</button>
      <button onClick={onGraphicsClick} disabled={locked} className="px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border">◈ Graphics</button>
      <button onClick={() => setDrawMode(!drawMode)} disabled={locked}
        className={`px-4 py-2 border rounded-lg text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
          drawMode ? 'border-accent bg-accent/10 text-accent' : 'bg-surface border-border text-textPrimary hover:border-accent'
        }`}>
        ✎ Draw{drawMode ? ' (on)' : ''}
      </button>
      {drawMode && !locked && (
        <div className="flex items-center gap-3 px-1">
          <label className="flex items-center gap-1 text-xs text-textMuted" title="Draw colour">
            <span>Colour</span>
            <input type="color" value={drawColour} onChange={e => setDrawColour(e.target.value)}
              className="w-7 h-7 p-0 border-0 bg-transparent" aria-label="Draw colour" />
          </label>
          <label className="flex items-center gap-1 text-xs text-textMuted" title="Thickness">
            <span>Thickness</span>
            <input type="range" min={0.004} max={0.03} step={0.002} value={drawWidth}
              onChange={e => setDrawWidth(Number(e.target.value))} aria-label="Draw thickness" />
          </label>
        </div>
      )}

      {colourways.length > 0 && (
        <div>
          <p className="text-xs text-textMuted mb-1.5">Cap colour</p>
          <div className="flex flex-wrap gap-2">
            {colourways.map(c => (
              <button key={`${c.hex}-${c.name}`} onClick={() => setColourway(c)} aria-label={c.name} disabled={locked}
                className={`w-7 h-7 rounded-full border-2 disabled:opacity-50 disabled:cursor-not-allowed ${colourway?.hex === c.hex ? 'border-accent' : 'border-border'}`}
                style={{ background: c.hex }} title={c.name} />
            ))}
          </div>
        </div>
      )}

      <button onClick={onRender} disabled={locked || rendering || rendered}
        className="mt-auto px-4 py-3 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-semibold disabled:opacity-50 transition-colors">
        {rendered ? 'Design saved ✓' : rendering ? 'Saving…' : 'Done designing'}
      </button>
    </div>
  )
}
