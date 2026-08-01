/**
 * Measured text boxes for placed text elements, keyed by element id.
 *
 * Text has no stored width/height — it auto-sizes to its glyphs, and only the
 * live Konva node knows its real box (`getClientRect`). Anything outside the
 * canvas that needs that box (the Adjust panel's Centre button, which must put
 * the text's own centre on the stage centre) would otherwise be stuck with the
 * `estimateTextBox` heuristic, which is a few px out for straight text and a
 * long way out for curved text.
 *
 * A module-level map rather than store state on purpose: this is a measurement
 * OF the render, not part of the design. Putting it in canvasStore would write
 * it into the persisted `canvas_design` blob and re-render the canvas on every
 * measurement. Only the live `TextNode` publishes here — FaceThumbnails draws
 * text at thumbnail scale and must never overwrite a full-stage measurement.
 *
 * Stale entries for deleted elements are harmless: ids are random and unique,
 * so a stale box can never be read back by a different element.
 */

const boxes = new Map<string, { w: number; h: number }>()

export function setMeasuredTextBox(id: string, w: number, h: number): void {
  boxes.set(id, { w, h })
}

export function getMeasuredTextBox(id: string): { w: number; h: number } | null {
  return boxes.get(id) ?? null
}

/** Tests only — the map outlives a component tree by design. */
export function clearMeasuredTextBoxes(): void {
  boxes.clear()
}
