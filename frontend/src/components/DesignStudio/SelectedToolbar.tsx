import { useEffect, useRef, useState } from 'react'
import { useCanvasStore, LINE_SHAPES, TEXT_PLACEHOLDER } from '../../store/canvasStore'
import { WEB_SAFE_FONTS, GOOGLE_FONTS } from '../../lib/fonts'

/** The panel may never eat more than this share of the column it shares with
 *  the cap. A share, not a fixed height, because the column's height is
 *  viewport-derived. */
const MAX_SHARE = 1 / 3
/** Floor, so the cap is never so tight the panel is unusable — below this it
 *  scrolls internally instead of shrinking further. */
const MIN_MAX_H = 72
/** Below this COLUMN width the group captions are dropped to tooltips. Measured
 *  off the column, not a Tailwind breakpoint: `xl:` and friends key off the
 *  VIEWPORT, but the pressure here is the column's own width — the studio is a
 *  three-column layout, so a 1536px window still leaves this column ~400-500px
 *  and the captions would have stayed visible exactly where they cost most. */
const COMPACT_BELOW = 640

/** Header label per element type — the panel names what it is adjusting, so a
 *  customer who selects something knows the panel that just appeared is for it. */
const ADJUST_LABELS: Record<string, string> = {
  text: 'Text', image: 'Image', shape: 'Shape', drawing: 'Drawing',
}

export function SelectedToolbar() {
  const activeFace = useCanvasStore(s => s.activeFace)
  const faces = useCanvasStore(s => s.faces)
  const selectedId = useCanvasStore(s => s.selectedId)
  const update = useCanvasStore(s => s.updateElement)
  const remove = useCanvasStore(s => s.removeElement)
  const duplicate = useCanvasStore(s => s.duplicate)
  const reorder = useCanvasStore(s => s.reorder)

  const el = faces[activeFace].find(e => e.id === selectedId)

  // Cap the controls region at a share of the column, MEASURED. The previous
  // `max-h-[9rem] md:max-h-[45vh]` could not be right on both: `vh` is a
  // fraction of the VIEWPORT, but this panel lives in a column shorter than the
  // viewport by the chat and two header bars, so `45vh` exceeded the region it
  // was bounding — and because the root is `sticky top-0`, an over-cap panel
  // stays pinned for the whole scroll range and the cap never comes back.
  // Measuring removes the guess and needs no breakpoint.
  //
  // No feedback loop: the column's height comes from the flex row above it
  // (viewport-derived, content-independent), so the panel resizing can never
  // change the number it just read — the same property CanvasStage relies on.
  // Both observers are feature-detected: jsdom ships neither, and constructing
  // one unconditionally throws through every test that mounts Surface.
  const rootRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLInputElement>(null)
  const [maxH, setMaxH] = useState<number | null>(null)
  const [compact, setCompact] = useState(true)   // assume tight until measured
  useEffect(() => {
    const col = rootRef.current?.parentElement
    if (!col) return
    const measure = () => {
      setMaxH(Math.max(MIN_MAX_H, Math.round(col.clientHeight * MAX_SHARE)))
      setCompact(col.clientWidth < COMPACT_BELOW)
    }
    measure()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    ro?.observe(col)
    window.addEventListener('resize', measure)
    return () => { ro?.disconnect(); window.removeEventListener('resize', measure) }
    // Keyed on the selected element: with nothing selected this component
    // renders null, so there is no DOM and no parent to measure. Re-running as
    // the panel mounts is what gets the first measurement at all.
  }, [el?.id])

  // Focus+select ONLY while the content is still the untouched placeholder, so
  // a freshly added element can be typed straight over. Re-selecting an element
  // the customer already edited must not steal focus — on a phone that pops the
  // keyboard over the canvas. Keyed on the id alone: the guard goes false on the
  // first keystroke, so re-running per character would be pointless churn.
  useEffect(() => {
    if (el?.type !== 'text' || el.content !== TEXT_PLACEHOLDER) return
    contentRef.current?.focus()
    contentRef.current?.select()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [el?.id])

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

  // sticky: the centre column of Surface is the scroll container, so this pins
  // the panel to the top of the canvas area. It used to render BELOW the cap,
  // which on a phone (chat already owns 45vh) put it under the fold entirely.
  // The controls region scrolls within itself so a wrapped toolbar can never
  // push the cap off-screen.
  //
  // Everything here is deliberately DENSE: this panel shares a column with the
  // cap, and CanvasStage sizes the cap from the height left over beside it —
  // so every pixel the panel takes is a pixel off the design surface. At its
  // old sizing it measured ~174px in a 410px column, which drove the stage
  // onto its 280px floor.
  return (
    <div ref={rootRef} data-testid="adjust-panel"
      className="sticky top-0 z-20 w-full shrink-0 bg-surface border border-accent rounded-xl overflow-hidden shadow-sm">
      <div className="bg-accent text-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide">
        Adjust — {ADJUST_LABELS[el.type] ?? 'Element'}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 p-2 overflow-y-auto"
        style={maxH ? { maxHeight: maxH } : undefined}>
      {el.type === 'text' && (
        <>
          {/* The content field is the point of a text element, so it gets its
              own full-width labelled row above the styling controls. It used to
              be a 112px unlabelled box wedged between the font dropdown and the
              sliders, which customers did not find. `basis-full` makes it claim
              a whole line of the wrapping flex row. */}
          <label className="basis-full flex flex-col gap-0.5">
            <span className="text-[10px] uppercase tracking-wide text-textMuted leading-none">Your text</span>
            <input ref={contentRef} value={el.content ?? ''}
              onChange={e => update(el.id, { content: e.target.value })}
              className="w-full bg-base border border-accent rounded px-2 py-1 text-sm text-textPrimary focus:outline-none focus:ring-2 focus:ring-accent/40"
              aria-label="Text content" />
          </label>
          <select value={el.font ?? 'Arial'} onChange={e => update(el.id, { font: e.target.value })}
            className="bg-base border border-border rounded px-1.5 py-0.5 text-xs max-w-[7rem]" aria-label="Font"
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
            className="w-6 h-6 p-0 border-0 bg-transparent" aria-label="Text colour" />
          <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Font size">
            <span aria-hidden="true">A</span>
            <input type="range" className="w-20" min={12} max={96} value={el.fontSize ?? 36}
              onChange={e => update(el.id, { fontSize: Number(e.target.value) })} aria-label="Font size" />
          </label>
          <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Curve the text">
            <span aria-hidden="true">Curve</span>
            <input type="range" className="w-20" min={-100} max={100} step={5} value={el.curve ?? 0}
              onChange={e => update(el.id, { curve: Number(e.target.value) })} aria-label="Curve text" />
          </label>
        </>
      )}
      {el.type === 'image' && (
        <label className="flex items-center gap-1.5 text-xs text-textPrimary"
          title="Flag this image so the design team knocks out its background when producing the artwork">
          <input type="checkbox" checked={!!el.removeBg}
            onChange={e => update(el.id, { removeBg: e.target.checked })} />
          Remove background
        </label>
      )}
      {el.type === 'drawing' && (
        <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Stroke colour">
          <span>Colour</span>
          <input type="color" value={el.stroke ?? '#111827'} onChange={e => update(el.id, { stroke: e.target.value })}
            className="w-6 h-6 p-0 border-0 bg-transparent" aria-label="Stroke colour" />
        </label>
      )}
      {el.type === 'shape' && (LINE_SHAPES.includes(el.shapeKind ?? 'rect') ? (
        <>
          <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Colour">
            <span>Colour</span>
            <input type="color" value={el.fill ?? '#111827'} onChange={e => update(el.id, { fill: e.target.value })}
              className="w-6 h-6 p-0 border-0 bg-transparent" aria-label="Shape colour" />
          </label>
          <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Thickness">
            <span>Width</span>
            <input type="range" className="w-20" min={2} max={30} value={el.strokeWidth ?? 6}
              onChange={e => update(el.id, { strokeWidth: Number(e.target.value) })} aria-label="Line thickness" />
          </label>
        </>
      ) : (
        <>
          <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Fill colour">
            <span>Fill</span>
            <input type="color" value={el.fill ?? '#2563eb'} onChange={e => update(el.id, { fill: e.target.value, filled: true })}
              className="w-6 h-6 p-0 border-0 bg-transparent" aria-label="Fill colour" />
          </label>
          <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Border colour">
            <span>Border</span>
            <input type="color" value={el.stroke ?? '#111827'} onChange={e => update(el.id, { stroke: e.target.value })}
              className="w-6 h-6 p-0 border-0 bg-transparent" aria-label="Border colour" />
          </label>
          <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Border width">
            <span>W</span>
            <input type="range" className="w-20" min={0} max={24} value={el.strokeWidth ?? 0}
              onChange={e => update(el.id, { strokeWidth: Number(e.target.value) })} aria-label="Border width" />
          </label>
          <button
            onClick={() => update(el.id, el.filled === false
              ? { filled: true }
              : { filled: false, strokeWidth: Math.max(el.strokeWidth ?? 0, 4) })}
            className="px-1.5 py-0.5 text-xs border border-border rounded"
            title="Toggle filled / outline"
          >
            {el.filled === false ? 'Outline' : 'Filled'}
          </button>
        </>
      ))}
      <Sep />

      {/* Rotate — curved arrows (⟲/⟳), unmistakably a rotate control and
          never confusable with Move's straight directional arrows or Layer
          order's forward/back glyphs below. */}
      <Group compact={compact} label="Rotate">
        <button onClick={() => rotateBy(-45)} className={btn} title="Rotate 45° left" aria-label="Rotate left 45 degrees">⟲</button>
        <input type="number" value={Math.round(el.rotation ?? 0)} onChange={e => update(el.id, { rotation: norm360(Number(e.target.value) || 0) })}
          className="w-11 bg-base border border-border rounded px-1 py-0.5 text-xs text-textPrimary"
          aria-label="Rotation degrees" title="Set an exact rotation in degrees" />
        <button onClick={() => rotateBy(45)} className={btn} title="Rotate 45° right" aria-label="Rotate right 45 degrees">⟳</button>
        <button onClick={() => update(el.id, { rotation: 0 })} className={`${btn} text-xs`} title="Reset rotation to 0°" aria-label="Reset rotation">Reset</button>
      </Group>

      <Sep />

      {/* Move — plain directional arrows, nudging POSITION. Deliberately a
          different glyph family from Rotate (⟲/⟳) and Layer order (▲▼ below)
          so the three controls can never be mistaken for each other. */}
      <Group compact={compact} label="Move">
        <button onClick={() => nudge(-NUDGE, 0)} className={btn} title="Move left" aria-label="Nudge left">←</button>
        <button onClick={() => nudge(0, -NUDGE)} className={btn} title="Move up" aria-label="Nudge up">↑</button>
        <button onClick={() => nudge(0, NUDGE)} className={btn} title="Move down" aria-label="Nudge down">↓</button>
        <button onClick={() => nudge(NUDGE, 0)} className={btn} title="Move right" aria-label="Nudge right">→</button>
      </Group>

      {canResize && (
        <>
          <Sep />
          <Group compact={compact} label="Size">
            <button onClick={() => resize(1 / SIZE_FACTOR)} className={btn} title="Make smaller" aria-label="Decrease size">−</button>
            <button onClick={() => resize(SIZE_FACTOR)} className={btn} title="Make larger" aria-label="Increase size">+</button>
          </Group>
        </>
      )}

      <Sep />

      {/* Layer order — deliberately TEXT + stacked-square glyphs, never the
          bare ↑/↓ Move already owns (that collision was the confusing-arrows
          bug this fix corrects). "Forward" = toward the top of the stack (in
          front of whatever is on top of it); "Back" = toward the bottom —
          unrelated to on-screen position, which is what Move controls. */}
      <Group compact={compact} label="Layer order">
        <button onClick={() => reorder(el.id, 'up')} className={`${btn} text-xs`}
          title="Bring this element forward, in front of whatever is on top of it" aria-label="Bring forward">▲Fwd</button>
        <button onClick={() => reorder(el.id, 'down')} className={`${btn} text-xs`}
          title="Send this element back, behind whatever is under it" aria-label="Send back">▼Back</button>
      </Group>

      <Sep />

      <Group compact={compact} label="Actions">
        <button onClick={() => duplicate(el.id)} className={btn} title="Duplicate this element" aria-label="Duplicate">Duplicate</button>
        <button onClick={() => remove(el.id)} className="px-1.5 py-0.5 text-xs text-red-600 border border-red-200 rounded hover:bg-red-50 transition-colors"
          title="Delete this element" aria-label="Delete">Delete</button>
      </Group>
      </div>
    </div>
  )
}

/** Shared small-caption + button-row wrapper for one toolbar section, so every
 *  group of controls is visually separated and machine-labelled (role="group"
 *  + aria-label) as well as sighted-labelled (the caption) — and wraps as a
 *  unit on narrow widths instead of its buttons scattering individually. */
function Group({ label, compact, children }:
  { label: string; compact: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5" role="group" aria-label={label} title={label}>
      <span className={compact
        ? 'hidden'
        : 'block text-[10px] uppercase tracking-wide text-textMuted leading-none'}>{label}</span>
      <div className="flex items-center gap-1">{children}</div>
    </div>
  )
}

/** Vertical divider between toolbar sections (hidden on narrow widths, where
 *  groups wrap onto their own line and a divider would just look stray). */
function Sep() {
  return <div className="hidden sm:block w-px self-stretch bg-border" aria-hidden="true" />
}

const btn = 'px-1.5 py-0.5 text-xs border border-border rounded hover:border-accent transition-colors'
