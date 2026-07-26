import type Konva from 'konva'

/** Decode a base64 data URL (image/png) into a File for multipart upload. */
export function dataUrlToFile(dataUrl: string, name: string): File {
  const [meta, b64] = dataUrl.split(',')
  const mime = /:(.*?);/.exec(meta)?.[1] ?? 'image/png'
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new File([bytes], name, { type: mime })
}

/** Konva `name` marking a node the layout-guide export must exclude (the product
 * photo background + colour tint). See flattenStage. */
export const FLATTEN_HIDE_NAME = 'flatten-hide'

/**
 * Every export is this many pixels on a side, whatever the screen.
 *
 * The on-screen stage is now sized to the viewport (CanvasStage scales the fixed
 * 480 logical space), so a hardcoded pixelRatio would make a laptop's layout
 * guide smaller than a desktop's. Deriving the ratio from the stage's live width
 * pins the output instead — and it still evaluates to the historical `2` when
 * the stage happens to render at 480.
 */
export const EXPORT_EDGE_PX = 960

/** pixelRatio that renders `stage` at EXPORT_EDGE_PX, unless one is passed. */
function exportRatio(stage: Konva.Stage, pixelRatio?: number): number {
  if (pixelRatio !== undefined) return pixelRatio
  const w = stage.width() || 480
  return EXPORT_EDGE_PX / w
}

/** Konva `name` for UI-only overlays (e.g. the bg-remove badge) that must NEVER
 * appear in ANY export — neither the layout guide nor the WYSIWYG preview. */
export const EXPORT_HIDE_NAME = 'export-hide'

/** Hide every stage node whose space-separated `name` contains any of `names`;
 * returns the nodes hidden so the caller can restore them. */
function hideByName(stage: Konva.Stage, names: string[]): Konva.Node[] {
  const hidden = stage.find((node: Konva.Node) => {
    const name = typeof node.name === 'function' ? node.name() : ''
    return typeof name === 'string' && name.split(/\s+/).some(n => names.includes(n))
  })
  hidden.forEach(n => n.hide())
  return hidden
}

/**
 * Flatten the placed decorations to a transparent PNG data URL — the "layout
 * guide" sent to the image model.
 *
 * CRITICAL: the guide carries ONLY the decorations the customer placed (at their
 * exact position/size/rotation) on a TRANSPARENT background. The product-photo
 * background and colour tint (tagged `name="flatten-hide"`) are hidden for the
 * export. A flattened mock that already shows the finished-looking product makes
 * the image model return that flat mock verbatim ("it just exported the canvas")
 * instead of compositing the decorations onto the real product photo. Hiding the
 * background forces the model to re-render photorealistically.
 *
 * Nodes are restored after export (in a finally) so the on-screen canvas is
 * unchanged.
 */
export function flattenStage(stage: Konva.Stage, pixelRatio?: number): string {
  const ratio = exportRatio(stage, pixelRatio)
  const hidden = hideByName(stage, [FLATTEN_HIDE_NAME, EXPORT_HIDE_NAME])
  try {
    // Re-render the scene with the background hidden before rasterising.
    stage.draw()
    return stage.toDataURL({ pixelRatio: ratio, mimeType: 'image/png' })
  } finally {
    hidden.forEach(n => n.show())
    stage.draw()
  }
}

/**
 * Flatten the FULL canvas exactly as seen on screen — product photo + colour
 * tint + placed decorations (nothing hidden). This is the WYSIWYG "your design"
 * export emailed to the customer as their own layout (distinct from the
 * decorations-only layout guide the image model consumes).
 */
export function flattenFull(stage: Konva.Stage, pixelRatio?: number): string {
  const ratio = exportRatio(stage, pixelRatio)
  // Keep the product photo + tint, but still drop UI-only overlays (bg-remove badge).
  const hidden = hideByName(stage, [EXPORT_HIDE_NAME])
  try {
    stage.draw()
    return stage.toDataURL({ pixelRatio: ratio, mimeType: 'image/png' })
  } finally {
    hidden.forEach(n => n.show())
    stage.draw()
  }
}
