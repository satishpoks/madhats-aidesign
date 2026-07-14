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

/** Set CSS custom properties from a brand. Unset fields are left untouched so the
 *  Tailwind fallbacks (current MadHats look) apply. */
export function applyBrandVars(brand: Brand): void {
  const root = document.documentElement
  if (brand.primary_colour) {
    root.style.setProperty('--brand-primary', brand.primary_colour)
    root.style.setProperty('--brand-primary-hover', darken(brand.primary_colour))
  }
  if (brand.header_bg) root.style.setProperty('--brand-header-bg', brand.header_bg)
  if (brand.header_text) root.style.setProperty('--brand-header-text', brand.header_text)
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
