// Curated font families for the canvas text tool. Konva renders text with the
// browser's font, so a family must actually be LOADED before it draws/flattens
// — the Google families here are requested by the <link> in index.html, and
// ensureFont() waits for a specific family to be ready before a redraw/export.

export interface FontOption {
  label: string
  family: string
  google?: boolean
}

export const WEB_SAFE_FONTS: FontOption[] = [
  { label: 'Arial', family: 'Arial' },
  { label: 'Impact', family: 'Impact' },
  { label: 'Georgia', family: 'Georgia' },
  { label: 'Times New Roman', family: 'Times New Roman' },
  { label: 'Courier New', family: 'Courier New' },
  { label: 'Verdana', family: 'Verdana' },
  { label: 'Trebuchet MS', family: 'Trebuchet MS' },
]

// Kept in sync with the family list requested in index.html.
export const GOOGLE_FONTS: FontOption[] = [
  { label: 'Roboto', family: 'Roboto', google: true },
  { label: 'Open Sans', family: 'Open Sans', google: true },
  { label: 'Montserrat', family: 'Montserrat', google: true },
  { label: 'Poppins', family: 'Poppins', google: true },
  { label: 'Oswald', family: 'Oswald', google: true },
  { label: 'Raleway', family: 'Raleway', google: true },
  { label: 'Playfair Display', family: 'Playfair Display', google: true },
  { label: 'Merriweather', family: 'Merriweather', google: true },
  { label: 'Bebas Neue', family: 'Bebas Neue', google: true },
  { label: 'Anton', family: 'Anton', google: true },
  { label: 'Archivo Black', family: 'Archivo Black', google: true },
  { label: 'Righteous', family: 'Righteous', google: true },
  { label: 'Abril Fatface', family: 'Abril Fatface', google: true },
  { label: 'Lobster', family: 'Lobster', google: true },
  { label: 'Pacifico', family: 'Pacifico', google: true },
  { label: 'Caveat', family: 'Caveat', google: true },
  { label: 'Bangers', family: 'Bangers', google: true },
  { label: 'Permanent Marker', family: 'Permanent Marker', google: true },
]

export const FONT_OPTIONS: FontOption[] = [...WEB_SAFE_FONTS, ...GOOGLE_FONTS]

/**
 * Resolve once the given font family is loaded and ready for Konva to render.
 * Best-effort: uses the CSS Font Loading API where available; a fallback render
 * is acceptable if it isn't (or the font can't load).
 */
export async function ensureFont(family: string, sizePx = 48): Promise<void> {
  try {
    if (typeof document !== 'undefined' && document.fonts?.load) {
      await document.fonts.load(`${sizePx}px '${family}'`)
    }
  } catch {
    // ignore — a fallback font render is acceptable
  }
}
