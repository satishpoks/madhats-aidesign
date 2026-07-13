import type { Colourway } from '../../store/canvasStore'
import { useCanvasStore } from '../../store/canvasStore'

interface ToolRailProps {
  onAddText: () => void
  onUploadClick: () => void
  onGraphicsClick: () => void
  colourways: Colourway[]
  onRender: () => void
  rendering: boolean
}

export function ToolRail({ onAddText, onUploadClick, onGraphicsClick, colourways, onRender, rendering }: ToolRailProps) {
  const colourway = useCanvasStore(s => s.colourway)
  const setColourway = useCanvasStore(s => s.setColourway)
  return (
    <div className="flex flex-col gap-3 p-4 w-full md:w-64">
      <button onClick={onAddText} className="px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors">+ Add text</button>
      <button onClick={onUploadClick} className="px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors">↑ Upload image</button>
      <button onClick={onGraphicsClick} className="px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors">◈ Graphics</button>

      {colourways.length > 0 && (
        <div>
          <p className="text-xs text-textMuted mb-1.5">Cap colour</p>
          <div className="flex flex-wrap gap-2">
            {colourways.map(c => (
              <button key={`${c.hex}-${c.name}`} onClick={() => setColourway(c)} aria-label={c.name}
                className={`w-7 h-7 rounded-full border-2 ${colourway?.hex === c.hex ? 'border-accent' : 'border-border'}`}
                style={{ background: c.hex }} title={c.name} />
            ))}
          </div>
        </div>
      )}

      <button onClick={onRender} disabled={rendering}
        className="mt-auto px-4 py-3 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-semibold disabled:opacity-50 transition-colors">
        {rendering ? 'Rendering…' : 'See it rendered'}
      </button>
    </div>
  )
}
