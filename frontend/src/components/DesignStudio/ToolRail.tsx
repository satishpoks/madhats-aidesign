import type { Colourway } from '../../store/canvasStore'
import { useCanvasStore } from '../../store/canvasStore'

type Tool = 'upload' | 'text' | 'shape'

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
  /** REWORK_CANVAS: hide the render/"Done designing" button entirely — the
   *  per-step Done button is the only submit during a rework pass. */
  hideRender?: boolean
  /** v2: when set, ONLY these tool buttons are enabled. */
  allowedTools?: Set<Tool>
  /** v2: the tool to visually highlight (accent glow + pulse). */
  highlightTool?: Tool | null
}

export function ToolRail({ onAddText, onUploadClick, onGraphicsClick, colourways, onRender, rendering, rendered, locked, hideRender, allowedTools, highlightTool }: ToolRailProps) {
  const colourway = useCanvasStore(s => s.colourway)
  const setColourway = useCanvasStore(s => s.setColourway)
  const drawMode = useCanvasStore(s => s.drawMode)
  const setDrawMode = useCanvasStore(s => s.setDrawMode)
  const drawColour = useCanvasStore(s => s.drawColour)
  const setDrawColour = useCanvasStore(s => s.setDrawColour)
  const drawWidth = useCanvasStore(s => s.drawWidth)
  const setDrawWidth = useCanvasStore(s => s.setDrawWidth)

  // A tool is disabled if the whole rail is locked, or (v2) it's not in the
  // allowed set. When allowedTools is undefined we fall back to the legacy
  // `locked` behaviour so v1 is unaffected.
  const toolDisabled = (t: Tool) =>
    !!locked || (allowedTools !== undefined && !allowedTools.has(t))
  // A3: the upload tool is intentionally NOT emphasised in the main flow — the
  // chips do the real work, and ask_logo_bg only holds the tool open (to keep
  // the just-placed logo selectable) without wanting to draw the eye to it.
  // Its `allowedTools`/`toolDisabled` behaviour is untouched (still enabled +
  // unlocked); only the ring + pulse are dropped. Other tools still highlight.
  const hi = (t: Tool) =>
    t !== 'upload' && highlightTool === t
      ? ' ring-2 ring-accent ring-offset-2 ring-offset-surface animate-pulse'
      : ''

  // Draw + cap-colour have no `Tool` entry in `allowedTools` (v2 never offers
  // either), so they were previously gated on `locked` alone and stayed
  // enabled through every v2 step — including ASK_ANYTHING_ELSE/ASK_QUANTITY
  // where the backend's directive is `allowed_tools: []` ("all locked").
  // `allowedTools !== undefined` means "v2 is driving this turn" — gate both
  // on that too, in addition to the legacy `locked` flag. v1 (no
  // `allowedTools` prop) is unaffected.
  const railGated = allowedTools !== undefined
  const drawOrColourDisabled = !!locked || railGated

  return (
    <div className="flex flex-col gap-3 p-4 w-full md:w-64">
      <button onClick={onAddText} disabled={toolDisabled('text')} className={`px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border${hi('text')}`}>+ Add text</button>
      <button onClick={onUploadClick} disabled={toolDisabled('upload')} className={`px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border${hi('upload')}`}>↑ Upload image</button>
      <button onClick={onGraphicsClick} disabled={toolDisabled('shape')} className={`px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border${hi('shape')}`}>◈ Graphics</button>
      <button onClick={() => setDrawMode(!drawMode)} disabled={drawOrColourDisabled}
        className={`px-4 py-2 border rounded-lg text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
          drawMode ? 'border-accent bg-accent/10 text-accent' : 'bg-surface border-border text-textPrimary hover:border-accent'
        }`}>
        ✎ Draw{drawMode ? ' (on)' : ''}
      </button>
      {drawMode && !drawOrColourDisabled && (
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
              <button key={`${c.hex}-${c.name}`} onClick={() => setColourway(c)} aria-label={c.name} disabled={drawOrColourDisabled}
                className={`w-7 h-7 rounded-full border-2 disabled:opacity-50 disabled:cursor-not-allowed ${colourway?.hex === c.hex ? 'border-accent' : 'border-border'}`}
                style={{ background: c.hex }} title={c.name} />
            ))}
          </div>
        </div>
      )}

      {!hideRender && (
        <button onClick={onRender} disabled={locked || rendering || rendered}
          className="mt-auto px-4 py-3 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-semibold disabled:opacity-50 transition-colors">
          {rendered ? 'Design saved ✓' : rendering ? 'Saving…' : 'Done designing'}
        </button>
      )}
    </div>
  )
}
