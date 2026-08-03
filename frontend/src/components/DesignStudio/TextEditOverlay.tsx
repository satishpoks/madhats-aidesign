import { useEffect, useRef } from 'react'
import { useCanvasStore, type CanvasElement } from '../../store/canvasStore'
import { estimateTextBox } from '../../lib/canvasGeometry'
import { getMeasuredTextBox } from '../../lib/textMetrics'

/**
 * In-place text editing, opened by double-click (desktop) / double-tap
 * (mobile) on a text node — see TextNode's onDblClick/onDblTap.
 *
 * DELIBERATELY a plain DOM `<input>`, rendered by CanvasStage as a sibling of
 * the Konva `<Stage>` (never a Konva node) — the same construction as
 * Watermark.tsx, for the same reason: `stage.toDataURL()` (both
 * `flattenStage`, the layout guide, and `flattenFull`, the WYSIWYG preview)
 * can only ever see the Konva scene graph, so a plain DOM overlay is
 * invisible to both exports by construction, not by discipline.
 *
 * Flatten-safety: the underlying Konva text node is NEVER hidden while this
 * is open — every keystroke is written straight into canvasStore
 * (`updateElement` on `onChange`, not just on commit), so the Konva node is
 * always rendering the SAME content this input shows. A flatten mid-edit
 * therefore exports whatever the customer has typed so far — never the old
 * value, and never nothing. There is no separate "commit before flatten"
 * step to keep in sync with every flatten call site because there is nothing
 * to commit that isn't already live in the store.
 *
 * The background MUST be fully opaque, not translucent — found live in the
 * browser, not in jsdom (which can't render pixels): because the Konva node
 * underneath is never hidden and repaints on every keystroke with the SAME
 * content this input shows, a translucent background let both renders show
 * through at once, at very slightly different positions/widths (input vs.
 * canvas font metrics), producing a "double-exposure" ghosting artifact that
 * reads as garbled text (e.g. typing "SATISH" visibly rendered as "ATISHH").
 * Full opacity is what actually hides the duplicate — not a Konva-level hide.
 */
export function TextEditOverlay({ el, scale, stageW, stageH }: {
  el: CanvasElement
  scale: number
  stageW: number
  stageH: number
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  // Captured once, at mount, for Escape / empty-revert — NOT re-read on
  // re-render, since the live content is being overwritten on every keystroke.
  const originalContent = useRef(el.content ?? '')

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  function commit() {
    const current = useCanvasStore.getState().faces[useCanvasStore.getState().activeFace]
      .find(e => e.id === el.id)
    const trimmed = (current?.content ?? '').trim()
    // Empty input must not silently delete the element (and an invisible
    // empty text node is not useful either) — revert to whatever the element
    // said before this edit started, rather than leaving it blank.
    if (!trimmed) {
      useCanvasStore.getState().updateElement(el.id, { content: originalContent.current })
    }
    useCanvasStore.getState().stopEditingText()
  }

  function cancel() {
    useCanvasStore.getState().updateElement(el.id, { content: originalContent.current })
    useCanvasStore.getState().stopEditingText()
  }

  // Best-effort box for positioning: the real measured box once TextNode has
  // published one (matches curved text too — TextPath shares the same
  // `shapeRef` measurement in TextNode), the same heuristic estimate used
  // elsewhere (SelectedToolbar's recentre) before that. Curved text's true
  // glyph path isn't modelled here — the overlay sits over its bounding box,
  // not its arc, which is an accepted approximation (see task report).
  const box = getMeasuredTextBox(el.id) ?? estimateTextBox(el.content ?? '', el.fontSize ?? 36)

  // el.x/el.y are the normalised TOP-LEFT (see canvasGeometry's header
  // comment) — no centre-pivot math needed here, just scale into the stage's
  // CURRENT rendered pixel size. `stage.width()` is the displayed size, not
  // the logical STAGE_W/STAGE_H — `scale` (passed by CanvasStage) already
  // carries that ratio, exactly like every other on-stage pixel computation.
  const left = el.x * stageW * scale
  const top = el.y * stageH * scale
  // A little wider than the pre-edit box (not the exact box) so typing a few
  // more characters than the current wording doesn't immediately start
  // scrolling inside the input — still an approximation, since the box can't
  // know the final length in advance.
  const width = Math.max(box.w * scale * 1.2, 32)
  const height = Math.max(box.h * scale, 16)

  return (
    <input
      ref={inputRef}
      data-testid="text-edit-overlay"
      aria-label="Edit text"
      value={el.content ?? ''}
      onChange={e => useCanvasStore.getState().updateElement(el.id, { content: e.target.value })}
      onBlur={commit}
      onKeyDown={e => {
        if (e.key === 'Enter') { e.preventDefault(); commit() }
        else if (e.key === 'Escape') { e.preventDefault(); cancel() }
      }}
      // Rotation pivots at the CSS box centre, matching Konva's own
      // offsetX/offsetY = half-extents registration (see canvasGeometry.ts).
      //
      // Background is a FULLY OPAQUE colour (`bg-base`, the same opaque
      // colour the Adjust panel's own CONTENT field sits on) — see the
      // header comment on why partial opacity produced visible ghosting.
      // Text colour is deliberately fixed (`text-textPrimary`), not
      // `el.colour` — the element's own colour is only guaranteed to be
      // legible against the CAP, not against this edit box's background.
      style={{
        position: 'absolute',
        left, top, width, height,
        transform: `rotate(${el.rotation ?? 0}deg)`,
        transformOrigin: '50% 50%',
        fontFamily: el.font ?? 'Arial',
        fontSize: Math.max((el.fontSize ?? 36) * scale, 8),
        zIndex: 20,
        padding: '0 2px',
        margin: 0,
        boxSizing: 'border-box',
      }}
      className="border-2 border-canvasAccent rounded-sm bg-base text-textPrimary outline-none"
    />
  )
}
