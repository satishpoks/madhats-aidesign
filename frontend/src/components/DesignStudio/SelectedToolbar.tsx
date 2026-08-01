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

/** Header label per element type — the panel names what it is adjusting, so a
 *  customer who selects something knows the panel that just appeared is for it. */
const ADJUST_LABELS: Record<string, string> = {
  text: 'Text', image: 'Image', shape: 'Shape', drawing: 'Drawing',
}

/** One click of ⟲ / ⟳. Was 45°, which is far too coarse to place a logo —
 *  eight positions on the whole circle. 12.5° gives fine control while still
 *  being one tap, and the readout formats to one decimal so the sequence reads
 *  0 · 12.5 · 25 · 37.5 rather than a lying rounded 13. */
const ROTATE_STEP = 12.5
const NUDGE = 0.02
const SIZE_FACTOR = 1.1

/** One decimal, but only when there is one — "45", not "45.0". */
function fmtDeg(v: number): string {
  const r = Math.round(v * 10) / 10
  return Number.isInteger(r) ? String(r) : r.toFixed(1)
}

/** `stacked` shares the centre column with the cap (mobile) — capped and
 *  sticky. `rail` sits in the tool rail below the Done button (desktop), where
 *  it competes with nothing, so it takes no height cap and needs no sticky. */
export function SelectedToolbar({ variant = 'stacked' }: { variant?: 'rail' | 'stacked' } = {}) {
  const activeFace = useCanvasStore(s => s.activeFace)
  const faces = useCanvasStore(s => s.faces)
  const selectedId = useCanvasStore(s => s.selectedId)
  const update = useCanvasStore(s => s.updateElement)
  const remove = useCanvasStore(s => s.removeElement)
  const duplicate = useCanvasStore(s => s.duplicate)
  const reorder = useCanvasStore(s => s.reorder)

  const el = faces[activeFace].find(e => e.id === selectedId)

  // Cap the controls region at a share of the column, MEASURED. `vh` cannot be
  // right here: it is a fraction of the VIEWPORT, but this panel lives in a
  // column shorter than the viewport by the chat and two header bars — and
  // because the root is `sticky top-0`, an over-cap panel stays pinned for the
  // whole scroll range and the cap never comes back.
  //
  // No feedback loop: the column's height comes from the flex row above it
  // (viewport-derived, content-independent), so the panel resizing can never
  // change the number it just read — the same property CanvasStage relies on.
  // The observer is feature-detected: jsdom ships none, and constructing one
  // unconditionally throws through every test that mounts Surface.
  const rootRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLInputElement>(null)
  const [maxH, setMaxH] = useState<number | null>(null)
  useEffect(() => {
    const col = rootRef.current?.parentElement
    if (!col) return
    const measure = () => {
      // Only the stacked variant caps its height: there it steals pixels from
      // the cap, which CanvasStage sizes from the leftover column height. In the
      // rail there is no cap beside it — the column's own overflow-y-auto
      // handles a long panel.
      setMaxH(variant === 'rail'
        ? null
        : Math.max(MIN_MAX_H, Math.round(col.clientHeight * MAX_SHARE)))
    }
    measure()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    ro?.observe(col)
    window.addEventListener('resize', measure)
    return () => { ro?.disconnect(); window.removeEventListener('resize', measure) }
    // Keyed on the selected element: with nothing selected this component
    // renders null, so there is no DOM and no parent to measure. Re-running as
    // the panel mounts is what gets the first measurement at all.
  }, [el?.id, variant])

  // Rail variant only: the panel mounts BELOW <ToolRail> inside an
  // overflow-y-auto column and deliberately takes no height cap, so on a short
  // column a newly-shown panel can land at or past the fold with no scroll cue
  // — verbatim the "selecting an element looks like it did nothing" bug this
  // panel's placement work exists to fix. `block: 'nearest'` so an
  // already-visible panel doesn't jump.
  //
  // Feature-detected like the observer above: jsdom leaves scrollIntoView
  // undefined on some element types, and calling it unconditionally throws
  // through every test that mounts this panel. The stacked variant is sticky at
  // the top of its own column and must not scroll.
  useEffect(() => {
    if (variant !== 'rail') return
    const node = rootRef.current
    if (node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'nearest' })
    }
  }, [el?.id, variant])

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
  const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
  const norm360 = (deg: number) => ((deg % 360) + 360) % 360
  const rotateBy = (delta: number) => update(el.id, { rotation: norm360((el.rotation ?? 0) + delta) })
  const nudge = (dx: number, dy: number) =>
    update(el.id, { x: clamp01((el.x ?? 0) + dx), y: clamp01((el.y ?? 0) + dy) })
  const recentre = () => update(el.id, { x: 0.5, y: 0.5 })
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
  const isLineShape = el.type === 'shape' && LINE_SHAPES.includes(el.shapeKind ?? 'rect')
  // An image's only control is the background flag, which is Content, not Style
  // — so an image has no Style section at all. An empty captioned block reads
  // as a broken panel, which is why every section is conditional.
  const hasContent = el.type === 'text' || el.type === 'image'
  const hasStyle = el.type === 'text' || el.type === 'shape' || el.type === 'drawing'

  return (
    <div ref={rootRef} data-testid="adjust-panel"
      className={`${variant === 'stacked' ? 'sticky top-0 z-20 ' : ''}w-full shrink-0 bg-surface border border-canvasAccent rounded-xl overflow-hidden shadow-sm`}>
      <div className="bg-canvasAccent text-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide">
        Adjust — {ADJUST_LABELS[el.type] ?? 'Element'}
      </div>
      <div data-testid="adjust-controls"
        className="flex flex-col px-2 overflow-y-auto"
        style={maxH ? { maxHeight: maxH } : undefined}>

        {hasContent && (
          <Section label="Content">
            {el.type === 'text' && (
              <label className="basis-full flex flex-col gap-0.5">
                <span className="text-[10px] uppercase tracking-wide text-textMuted leading-none">Your text</span>
                <input ref={contentRef} value={el.content ?? ''}
                  onChange={e => update(el.id, { content: e.target.value })}
                  className="w-full bg-base border border-canvasAccent rounded px-2 py-1 text-sm text-textPrimary focus:outline-none focus:ring-2 focus:ring-canvasAccent/40"
                  aria-label="Text content" />
              </label>
            )}
            {el.type === 'image' && (
              <label className="flex items-center gap-1.5 text-xs text-textPrimary"
                title="Flag this image so the design team knocks out its background when producing the artwork">
                <input type="checkbox" checked={!!el.removeBg}
                  onChange={e => update(el.id, { removeBg: e.target.checked })} />
                Remove background
              </label>
            )}
          </Section>
        )}

        {hasStyle && (
          <Section label="Style">
            {el.type === 'text' && (
              <>
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
            {el.type === 'drawing' && (
              <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Stroke colour">
                <span>Colour</span>
                <input type="color" value={el.stroke ?? '#111827'} onChange={e => update(el.id, { stroke: e.target.value })}
                  className="w-6 h-6 p-0 border-0 bg-transparent" aria-label="Stroke colour" />
              </label>
            )}
            {isLineShape && (
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
            )}
            {el.type === 'shape' && !isLineShape && (
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
                  className={btn}
                  title="Toggle filled / outline"
                >
                  {el.filled === false ? 'Outline' : 'Filled'}
                </button>
              </>
            )}
          </Section>
        )}

        <Section label="Position">
          {/* A game-controller cross, not a row of four arrows: the layout IS
              the label. The centre cell recentres — it fills the hole the cross
              leaves (an empty middle reads as a missing button) and is
              genuinely the fastest way to recover a dragged-off element. */}
          <div className="grid grid-cols-3 gap-1 w-max" role="group" aria-label="Move">
            <span />
            <button onClick={() => nudge(0, -NUDGE)} className={btn} title="Move up" aria-label="Nudge up">↑</button>
            <span />
            <button onClick={() => nudge(-NUDGE, 0)} className={btn} title="Move left" aria-label="Nudge left">←</button>
            <button onClick={recentre} className={btn} title="Centre on the cap" aria-label="Centre on the cap">⊕</button>
            <button onClick={() => nudge(NUDGE, 0)} className={btn} title="Move right" aria-label="Nudge right">→</button>
            <span />
            <button onClick={() => nudge(0, NUDGE)} className={btn} title="Move down" aria-label="Nudge down">↓</button>
            <span />
          </div>

          <div className="flex flex-col gap-1.5">
            {/* Curved arrows (⟲/⟳), never confusable with Move's straight
                directional arrows or Layer order's Fwd/Back glyphs below. */}
            <div className="flex items-center gap-1" role="group" aria-label="Rotate">
              <button onClick={() => rotateBy(-ROTATE_STEP)} className={btn}
                title="Rotate 12.5° left" aria-label="Rotate left 12.5 degrees">⟲</button>
              <input type="number" step={ROTATE_STEP} value={fmtDeg(el.rotation ?? 0)}
                onChange={e => {
                  // An in-progress decimal ("12.") reports value === "" for
                  // input[type=number] — Number('') || 0 would snap the
                  // rotation to 0 mid-keystroke. Ignore it and let the DOM
                  // keep the customer's partial input (the `value` prop below
                  // is unchanged, so React never overwrites what they typed).
                  if (e.target.value === '') return
                  update(el.id, { rotation: norm360(Number(e.target.value) || 0) })
                }}
                className="w-14 bg-base border border-border rounded px-1 py-0.5 text-xs text-textPrimary"
                aria-label="Rotation degrees" title="Set an exact rotation in degrees" />
              <button onClick={() => rotateBy(ROTATE_STEP)} className={btn}
                title="Rotate 12.5° right" aria-label="Rotate right 12.5 degrees">⟳</button>
              <button onClick={() => update(el.id, { rotation: 0 })} className={btn}
                title="Reset rotation to 0°" aria-label="Reset rotation">Reset</button>
            </div>
            {canResize && (
              <div className="flex items-center gap-1" role="group" aria-label="Size">
                <span className="text-[11px] text-textMuted">Size</span>
                <button onClick={() => resize(1 / SIZE_FACTOR)} className={btn} title="Make smaller" aria-label="Decrease size">−</button>
                <button onClick={() => resize(SIZE_FACTOR)} className={btn} title="Make larger" aria-label="Increase size">+</button>
              </div>
            )}
          </div>
        </Section>

        {/* Deliberately TEXT + stacked-square glyphs, never the bare ↑/↓ the
            D-pad above owns. "Forward" = toward the top of the stack; "Back" =
            toward the bottom — unrelated to on-screen position, which is what
            Move controls. */}
        <Section label="Layer order">
          <button onClick={() => reorder(el.id, 'up')} className={btn}
            title="Bring this element forward, in front of whatever is on top of it" aria-label="Bring forward">▲Fwd</button>
          <button onClick={() => reorder(el.id, 'down')} className={btn}
            title="Send this element back, behind whatever is under it" aria-label="Send back">▼Back</button>
        </Section>

        <Section label="Actions">
          <button onClick={() => duplicate(el.id)} className={btn} title="Duplicate this element" aria-label="Duplicate">Duplicate</button>
          <button onClick={() => remove(el.id)} className="px-1.5 py-0.5 text-xs text-red-600 border border-red-200 rounded hover:bg-red-50 transition-colors"
            title="Delete this element" aria-label="Delete">Delete</button>
        </Section>
      </div>
    </div>
  )
}

/** One captioned block of the panel. The caption is unconditional — the old
 *  panel hid it below a measured column width to save ~24px per group in the
 *  cramped centre column, but the panel now lives in the tool rail on desktop
 *  and the captions are the whole point of the restructure. `role="group"` +
 *  `aria-label` keep it machine-readable as well as sighted-labelled. */
function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section role="group" aria-label={label}
      className="flex flex-col gap-1 py-2 border-t border-border first:border-t-0">
      <span className="text-[10px] uppercase tracking-wide text-textMuted leading-none">{label}</span>
      <div className="flex flex-wrap items-start gap-2">{children}</div>
    </section>
  )
}

const btn = 'px-1.5 py-0.5 text-xs border border-border rounded hover:border-canvasAccent transition-colors'
