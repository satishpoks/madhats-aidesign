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
  /** Hide the render/"Done designing" button entirely rather than rendering
   *  it permanently disabled. Two callers: REWORK_CANVAS (the per-step Done
   *  button is the only submit during a rework pass) and, more broadly, ANY
   *  v2 turn — v2's finalize is chat-driven (`triggerFinalize`), so this
   *  button can never act there and a permanently-inert "Design saved ✓"
   *  button is dead chrome, same as a disabled tool. */
  hideRender?: boolean
  /** v2: when set, ONLY these tool buttons are rendered at all (not merely
   *  enabled) — a disabled column of every other tool reads as broken chrome,
   *  and on mobile its height comes straight out of the cap's own space. */
  allowedTools?: Set<Tool>
  /** v2: the tool to visually highlight (accent glow + pulse). */
  highlightTool?: Tool | null
  /** False while the canvas is not editable on this turn: render an empty rail
   *  rather than a column of disabled buttons. Defaults to true so v1 call
   *  sites (which never pass it) are unaffected. */
  toolsVisible?: boolean
  /** An image upload is in flight. Large artwork can take several seconds, and
   *  a button that looks idle invites a second click (and a second upload) —
   *  so the button reports progress and stops accepting clicks meanwhile. */
  uploading?: boolean
}

export function ToolRail({ onAddText, onUploadClick, onGraphicsClick, colourways, onRender, rendering, rendered, locked, hideRender, allowedTools, highlightTool, toolsVisible, uploading }: ToolRailProps) {
  const colourway = useCanvasStore(s => s.colourway)
  const setColourway = useCanvasStore(s => s.setColourway)
  const drawMode = useCanvasStore(s => s.drawMode)
  const setDrawMode = useCanvasStore(s => s.setDrawMode)
  const drawColour = useCanvasStore(s => s.drawColour)
  const setDrawColour = useCanvasStore(s => s.setDrawColour)
  const drawWidth = useCanvasStore(s => s.drawWidth)
  const setDrawWidth = useCanvasStore(s => s.setDrawWidth)

  // v1 (allowedTools undefined) renders every tool, disabled-not-hidden while
  // `locked` — that button IS the real submit path and must stay visible so
  // the customer can see what's coming. v2 (allowedTools set) renders ONLY
  // the tools the current step actually offers: a disabled "+ Add text" /
  // "Graphics" / "Draw" column next to the one live tool reads as a broken
  // app on a phone, where the rail's dead-chrome height is taken directly out
  // of the cap (Surface.tsx's mobile layout stacks the rail below the canvas
  // column). A rendered v2 tool is never locked — Surface always passes
  // `locked={false}` for a v2 turn — but `toolDisabled` still folds in
  // `locked` so a future caller that DID lock a v2 turn wouldn't accidentally
  // ship an enabled button.
  const showTool = (t: Tool) => allowedTools === undefined || allowedTools.has(t)
  const toolDisabled = (t: Tool) => !!locked || !showTool(t)
  // A3: the upload tool is intentionally NOT emphasised in the main flow — the
  // chips do the real work, and ask_logo_bg only holds the tool open (to keep
  // the just-placed logo selectable) without wanting to draw the eye to it.
  // Its `allowedTools`/`toolDisabled` behaviour is untouched (still enabled +
  // unlocked); only the ring + pulse are dropped. Other tools still highlight.
  const hi = (t: Tool) =>
    t !== 'upload' && highlightTool === t
      ? ' ring-2 ring-canvasAccent ring-offset-2 ring-offset-surface animate-pulse'
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

  // Width classes are duplicated deliberately between the two returns rather
  // than hoisted: they are the load-bearing part of the empty branch (the
  // responsive stage measures this column), and a shared constant is easy to
  // "clean up" out of the branch that needs it most.
  if (toolsVisible === false) {
    return <div data-testid="tool-rail-empty" className="flex flex-col gap-2.5 p-3 xl:p-4 w-full md:w-44 lg:w-52 xl:w-64" />
  }

  return (
    // Narrower on a laptop/iPad so the cap keeps the width it needs; full 16rem
    // back on a large desktop.
    <div className="flex flex-col gap-2.5 p-3 xl:p-4 w-full md:w-44 lg:w-52 xl:w-64">
      {showTool('text') && (
        <button onClick={onAddText} disabled={toolDisabled('text')} className={`px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-canvasAccent transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border${hi('text')}`}>+ Add text</button>
      )}
      {showTool('upload') && (
        <button onClick={onUploadClick} disabled={toolDisabled('upload') || !!uploading} className={`px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-canvasAccent transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border${hi('upload')}`}>
          {uploading ? (
            <span className="inline-flex items-center justify-center gap-2">
              <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
              Uploading…
            </span>
          ) : '↑ Upload image'}
        </button>
      )}
      {showTool('shape') && (
        <button onClick={onGraphicsClick} disabled={toolDisabled('shape')} className={`px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-canvasAccent transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border${hi('shape')}`}>◈ Graphics</button>
      )}
      {/* Draw + cap colour have no `Tool` entry in `allowedTools` — v2 never
          offers either, so `railGated` (v2 is driving this turn) hides them
          outright rather than rendering them disabled. v1 (railGated false)
          renders them exactly as before, disabled only while `locked`. */}
      {!railGated && (
        <button onClick={() => setDrawMode(!drawMode)} disabled={drawOrColourDisabled}
          className={`px-4 py-2 border rounded-lg text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
            drawMode ? 'border-canvasAccent bg-canvasAccent/10 text-canvasAccent' : 'bg-surface border-border text-textPrimary hover:border-canvasAccent'
          }`}>
          ✎ Draw{drawMode ? ' (on)' : ''}
        </button>
      )}
      {!railGated && drawMode && !drawOrColourDisabled && (
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

      {!railGated && colourways.length > 0 && (
        <div>
          <p className="text-xs text-textMuted mb-1.5">Cap colour</p>
          <div className="flex flex-wrap gap-2">
            {colourways.map(c => (
              <button key={`${c.hex}-${c.name}`} onClick={() => setColourway(c)} aria-label={c.name} disabled={drawOrColourDisabled}
                className={`w-7 h-7 rounded-full border-2 disabled:opacity-50 disabled:cursor-not-allowed ${colourway?.hex === c.hex ? 'border-canvasAccent' : 'border-border'}`}
                style={{ background: c.hex }} title={c.name} />
            ))}
          </div>
        </div>
      )}

      {!hideRender && (
        <button onClick={onRender} disabled={locked || rendering || rendered}
          className="mt-auto px-4 py-3 bg-canvasAccent hover:bg-canvasAccentHover text-white rounded-full text-sm font-semibold disabled:opacity-50 transition-colors">
          {rendered ? 'Design saved ✓' : rendering ? 'Saving…' : 'Done designing'}
        </button>
      )}
    </div>
  )
}
