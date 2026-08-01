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

/** Escape the three XML-significant characters before interpolating `text`
 *  into the SVG string below. `text` is not attacker-controlled (it's an
 *  admin-configured setting, not customer input), so this isn't a security
 *  fix — but an unescaped "&" (e.g. a store named "Smith & Co") would produce
 *  malformed SVG that fails to render as a background image at all. */
function escapeXml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function Watermark({ text }: { text: string }) {
  const tile = 220
  const safeText = escapeXml(text)
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${tile}" height="${tile}">
      <text x="50%" y="50%" transform="rotate(-30 ${tile / 2} ${tile / 2})"
            text-anchor="middle" dominant-baseline="middle"
            font-family="Helvetica, Arial, sans-serif" font-size="17"
            font-weight="700" letter-spacing="1.5"
            fill="rgb(255 255 255 / 0.42)">${safeText}</text>
    </svg>`
  // encodeURIComponent leaves `( )` unescaped (they're "unreserved" under the
  // older RFC2396 it implements). Left literal inside a quoted url("...")
  // string, real browsers parse them fine, but they aren't guaranteed to —
  // some CSS parsers (jsdom's `cssstyle`, used by this file's own tests,
  // among them) choke on a literal "(" nested inside a quoted url() token and
  // silently drop the whole declaration. Percent-encoding them explicitly
  // produces a byte-identical SVG with no such parser ambiguity anywhere.
  const dataUri = encodeURIComponent(svg).replace(/\(/g, '%28').replace(/\)/g, '%29')
  return (
    <div
      data-testid="canvas-watermark"
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 z-10 mix-blend-overlay"
      style={{
        backgroundImage: `url("data:image/svg+xml;utf8,${dataUri}")`,
        backgroundRepeat: 'repeat',
      }}
    />
  )
}
