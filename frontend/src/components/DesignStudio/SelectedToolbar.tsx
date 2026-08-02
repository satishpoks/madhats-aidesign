import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useCanvasStore, LINE_SHAPES, TEXT_PLACEHOLDER } from '../../store/canvasStore'
import { WEB_SAFE_FONTS, GOOGLE_FONTS } from '../../lib/fonts'
import { centredTopLeft, STAGE_W, STAGE_H } from '../../lib/canvasGeometry'
import { getMeasuredTextBox } from '../../lib/textMetrics'

/** Header label per element type — the panel names what it is adjusting, so a
 *  customer who selects something knows the panel that just appeared is for it. */
const ADJUST_LABELS: Record<string, string> = {
  text: 'Text', image: 'Image', shape: 'Shape', drawing: 'Drawing',
}

/** One click of ⟲ / ⟳. Was 45°, which is far too coarse to place a logo —
 *  eight positions on the whole circle. 11.25° divides the circle into 32, so
 *  the sequence lands exactly on every 45° and 90° (11.25 · 22.5 · 33.75 · 45)
 *  while still giving fine control in one tap. The readout keeps two decimals
 *  so it shows the true 11.25 rather than a lying rounded 11.3. */
const ROTATE_STEP = 11.25
const NUDGE = 0.02
const SIZE_FACTOR = 1.1

/** Up to two decimals, but only the ones there are — "45", not "45.00". */
function fmtDeg(v: number): string {
  return String(Math.round(v * 100) / 100)
}

/** Touch targets are bigger inside the mobile sheet than inside the desktop
 *  rail — the owner's report ("too small to see") was specifically about a
 *  phone, and the rail column already earned its current sizing from prior
 *  rounds of review. The desktop rail's classes are byte-identical to before
 *  this change; only the sheet branch is new. */
function controlBtn(variant: SelectedToolbarVariant): string {
  return variant === 'sheet'
    ? 'px-3 py-2 text-sm border border-border rounded-lg hover:border-canvasAccent transition-colors min-h-[2.5rem]'
    : 'px-1.5 py-0.5 text-xs border border-border rounded hover:border-canvasAccent transition-colors'
}
function deleteBtn(variant: SelectedToolbarVariant): string {
  return variant === 'sheet'
    ? 'px-3 py-2 text-sm text-red-600 border border-red-200 rounded-lg hover:bg-red-50 transition-colors min-h-[2.5rem]'
    : 'px-1.5 py-0.5 text-xs text-red-600 border border-red-200 rounded hover:bg-red-50 transition-colors'
}

/** `rail` sits in the tool rail below the Done button (desktop, `md` and
 *  above) — unchanged by this file, byte-for-byte, from before the mobile
 *  redesign below.
 *
 *  `sheet` is the mobile (`<md`) presentation: a bottom sheet FIXED to the
 *  viewport and rendered through a portal — see the portal comment near the
 *  bottom of this file for why. It replaced an earlier "stacked" variant that
 *  shared in-flow space with the centre column (sticky, height-capped to a
 *  measured share of that column); see git history / CLAUDE.md
 *  2026-08-01/02 for that design and why it read as "too small to see" on a
 *  real phone. */
export type SelectedToolbarVariant = 'rail' | 'sheet'

export function SelectedToolbar({ variant = 'sheet' }: { variant?: SelectedToolbarVariant } = {}) {
  const activeFace = useCanvasStore(s => s.activeFace)
  const faces = useCanvasStore(s => s.faces)
  const selectedId = useCanvasStore(s => s.selectedId)
  const update = useCanvasStore(s => s.updateElement)
  const remove = useCanvasStore(s => s.removeElement)
  const duplicate = useCanvasStore(s => s.duplicate)
  const reorder = useCanvasStore(s => s.reorder)

  const el = faces[activeFace].find(e => e.id === selectedId)

  const rootRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLInputElement>(null)

  // Sheet-only: collapsed (a slim handle + title bar, cap fully visible) vs
  // expanded (full controls). EXPANDED is the default — selecting an element
  // is an explicit request to adjust it, and defaulting to collapsed would
  // hide, behind an extra tap, the one control (`ask_logo_bg`'s
  // "Remove background" toggle) that some steps point the customer straight
  // at; it also would have meant every existing content/behaviour test below
  // (none of which "expand" anything — they render and immediately query for
  // a control) would need an extra step just to keep passing. Collapsing is
  // the deliberate, explicit action for "let me see the cap for a second"
  // — reachable at any time via the drag-handle, without deselecting (which
  // is the one thing that must never happen here: deselecting is how the
  // panel — and with it `ask_logo_bg`'s only route to the background-removal
  // toggle — disappears entirely).
  const [collapsed, setCollapsed] = useState(false)
  // A fresh selection always reopens expanded, even if the customer collapsed
  // the sheet to look at a different element a moment ago — the collapse is a
  // "let me see" gesture about THIS element, not a standing preference.
  useEffect(() => { setCollapsed(false) }, [el?.id])

  // Rail variant only: the panel mounts BELOW <ToolRail> inside an
  // overflow-y-auto column and deliberately takes no height cap, so on a short
  // column a newly-shown panel can land at or past the fold with no scroll cue
  // — verbatim the "selecting an element looks like it did nothing" bug this
  // panel's placement work exists to fix. `block: 'nearest'` so an
  // already-visible panel doesn't jump.
  //
  // Feature-detected like the observers elsewhere in this component tree:
  // jsdom leaves scrollIntoView undefined on some element types, and calling
  // it unconditionally throws through every test that mounts this panel. The
  // sheet variant is `position: fixed` to the viewport and must never scroll
  // itself into view — there's no "into view" for it to reach.
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
  // x/y are the element's normalised TOP-LEFT, so {0.5, 0.5} is NOT centred —
  // it puts the corner in the middle and the element half its own size down and
  // right of it. `centredTopLeft` backs the element's own centre out of the
  // stage centre, per type. Text gets its real measured box when the live node
  // has published one; the heuristic estimate is the fallback.
  const recentre = () =>
    update(el.id, centredTopLeft(el, STAGE_W, STAGE_H, getMeasuredTextBox(el.id)))
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

  const btn = controlBtn(variant)
  const isSheet = variant === 'sheet'
  const showControls = !isSheet || !collapsed

  const panel = (
    <div ref={rootRef} data-testid="adjust-panel"
      className={isSheet
        ? 'fixed inset-x-0 bottom-0 z-30 w-full shrink-0 flex flex-col bg-surface border-t border-canvasAccent rounded-t-2xl shadow-xl'
        : 'w-full shrink-0 bg-surface border border-canvasAccent rounded-xl overflow-hidden shadow-sm'}>

      {isSheet && (
        <button type="button" data-testid="adjust-sheet-handle"
          onClick={() => setCollapsed(c => !c)}
          aria-expanded={!collapsed}
          aria-label={collapsed ? 'Expand adjust panel' : 'Collapse adjust panel'}
          title="Drag or tap to collapse/expand"
          className="w-full shrink-0 flex justify-center py-2 touch-none">
          <span aria-hidden="true" className="h-1.5 w-10 rounded-full bg-border" />
        </button>
      )}

      <div className="bg-canvasAccent text-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide shrink-0">
        Adjust — {ADJUST_LABELS[el.type] ?? 'Element'}
      </div>

      {showControls && (
        <div data-testid="adjust-controls"
          className={`flex flex-col px-2 overflow-y-auto${isSheet ? ' max-h-[45vh] pb-3' : ''}`}>

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
                  title="Rotate 11.25° left" aria-label="Rotate left 11.25 degrees">⟲</button>
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
                  title="Rotate 11.25° right" aria-label="Rotate right 11.25 degrees">⟳</button>
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
            <button onClick={() => remove(el.id)} className={deleteBtn(variant)}
              title="Delete this element" aria-label="Delete">Delete</button>
          </Section>
        </div>
      )}
    </div>
  )

  // The sheet is rendered through a portal to document.body, deliberately NOT
  // as a normal child of the centre column, for a correctness reason beyond
  // styling: CanvasStage's `availableHeight` walks `col.children` and sums
  // each sibling's OWN `getBoundingClientRect().height` to work out how much
  // room is left for the cap. A `position: fixed` element still reports its
  // real rendered height from that call — fixed positioning takes it out of
  // normal *layout* flow, but not out of the DOM the sibling-height loop
  // walks — so left in place as a `col` child, the sheet would still be
  // subtracted from the cap's budget even though it no longer visually
  // occupies any of the column's space. Portalling it out of `col` entirely
  // is what makes "taking the panel out of flow gives the cap more room"
  // literally true rather than merely visually true. It does not need to be a
  // child of the centre column for anything else: `fixed` positions against
  // the viewport regardless of DOM ancestry (nothing between here and
  // `document.body` sets `transform`/`filter`/`contain`, which are the only
  // things that would change that).
  return isSheet ? createPortal(panel, document.body) : panel
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
