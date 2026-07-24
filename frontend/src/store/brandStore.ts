import { create } from 'zustand'
import type { Brand } from '../lib/types'
import { getStorefront } from '../lib/api'

/** Darken a #rrggbb (or #rgb) hex by `amt` (0..1). Used to derive a hover shade. */
function darken(hex: string, amt = 0.12): string {
  let h = hex.replace('#', '')
  if (h.length === 3) h = h.split('').map(c => c + c).join('')
  const n = parseInt(h, 16)
  const r = Math.max(0, Math.round(((n >> 16) & 255) * (1 - amt)))
  const g = Math.max(0, Math.round(((n >> 8) & 255) * (1 - amt)))
  const b = Math.max(0, Math.round((n & 255) * (1 - amt)))
  return '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('')
}

/** Pick a legible text colour (white or near-black) for a #rrggbb (or #rgb)
 *  background, using perceived luminance. Used when a store sets a header
 *  background but no explicit header text colour. */
function readableOn(hex: string): string {
  let h = hex.replace('#', '')
  if (h.length === 3) h = h.split('').map(c => c + c).join('')
  const n = parseInt(h, 16)
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255
  const luminance = 0.299 * r + 0.587 * g + 0.114 * b
  return luminance < 140 ? '#ffffff' : '#1A1D29'
}

/** Set CSS custom properties from a brand. Unset fields are left untouched so the
 *  Tailwind fallbacks (current MadHats look) apply. */
export function applyBrandVars(brand: Brand): void {
  const root = document.documentElement
  if (brand.primary_colour) {
    root.style.setProperty('--brand-primary', brand.primary_colour)
    root.style.setProperty('--brand-primary-hover', darken(brand.primary_colour))
  }
  if (brand.header_bg) root.style.setProperty('--brand-header-bg', brand.header_bg)
  if (brand.header_text) {
    root.style.setProperty('--brand-header-text', brand.header_text)
  } else if (brand.header_bg) {
    // A header bg without an explicit text colour would otherwise fall back to
    // the dark default (#1A1D29) — invisible on a dark header. Derive a legible
    // colour from the background so header text is always readable.
    root.style.setProperty('--brand-header-text', readableOn(brand.header_bg))
  }
}

interface BrandState {
  brand: Brand
  storeName: string
  personaName: string
  loaded: boolean
  init: () => Promise<void>
}

export const useBrandStore = create<BrandState>((set, get) => ({
  brand: {},
  storeName: '',
  personaName: '',
  loaded: false,
  init: async () => {
    if (get().loaded) return
    try {
      const sf = await getStorefront()
      applyBrandVars(sf.brand || {})
      set({ brand: sf.brand || {}, storeName: sf.name, personaName: sf.persona_name, loaded: true })
    } catch {
      // Storefront unreachable — keep Tailwind fallbacks; studio still works.
      set({ loaded: true })
    }
  },
}))
