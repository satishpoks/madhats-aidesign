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
export function flattenStage(stage: Konva.Stage, pixelRatio = 2): string {
  const hidden = stage.find((node: Konva.Node) => {
    const name = typeof node.name === 'function' ? node.name() : ''
    return typeof name === 'string' && name.split(/\s+/).includes(FLATTEN_HIDE_NAME)
  })
  hidden.forEach(n => n.hide())
  try {
    // Re-render the scene with the background hidden before rasterising.
    stage.draw()
    return stage.toDataURL({ pixelRatio, mimeType: 'image/png' })
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
export function flattenFull(stage: Konva.Stage, pixelRatio = 2): string {
  return stage.toDataURL({ pixelRatio, mimeType: 'image/png' })
}
