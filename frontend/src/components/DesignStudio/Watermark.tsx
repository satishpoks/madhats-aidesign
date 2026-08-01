/**
 * A repeating diagonal watermark drawn OVER a design.
 *
 * Deliberately a DOM sibling of the Konva stage, never a Konva layer. A DOM
 * node cannot appear in `stage.toDataURL()`, which makes two failure modes
 * impossible by construction rather than by discipline:
 *
 *  - the decorations-only layout guide (canvasFlatten.flattenStage) stays
 *    clean, so the image model never renders a watermark onto the cap;
 *  - the WYSIWYG preview (flattenFull) is never double-stamped, because
 *    delivery.py already burns the same text into the emailed copy server-side.
 *
 * That is also why there is no EXPORT_HIDE_NAME tagging here — there is
 * nothing for an export to hide.
 *
 * `text` comes from the admin-configured `watermark_text` app setting via
 * /storefront, so the canvas and the email always agree.
 */
export function Watermark({ text }: { text: string }) {
  const tile = 220
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${tile}" height="${tile}">
      <text x="50%" y="50%" transform="rotate(-30 ${tile / 2} ${tile / 2})"
            text-anchor="middle" dominant-baseline="middle"
            font-family="Helvetica, Arial, sans-serif" font-size="17"
            font-weight="700" letter-spacing="1.5"
            fill="rgb(255 255 255 / 0.42)">${text}</text>
    </svg>`
  return (
    <div
      data-testid="canvas-watermark"
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 z-10 mix-blend-overlay"
      style={{
        backgroundImage: `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`,
        backgroundRepeat: 'repeat',
      }}
    />
  )
}
