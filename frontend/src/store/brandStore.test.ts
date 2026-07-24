import { describe, it, expect, beforeEach } from 'vitest'
import { applyBrandVars } from './brandStore'

describe('applyBrandVars', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('style')
  })

  it('sets primary + derived hover + header vars', () => {
    applyBrandVars({ primary_colour: '#0055AA', header_bg: '#ffffff', header_text: '#111111' })
    const s = document.documentElement.style
    expect(s.getPropertyValue('--brand-primary')).toBe('#0055AA')
    expect(s.getPropertyValue('--brand-header-bg')).toBe('#ffffff')
    expect(s.getPropertyValue('--brand-header-text')).toBe('#111111')
    // hover is derived (darker) — just assert it was set to a hex
    expect(s.getPropertyValue('--brand-primary-hover')).toMatch(/^#[0-9a-fA-F]{6}$/)
  })

  it('no-ops for unset fields (keeps Tailwind fallbacks)', () => {
    applyBrandVars({})
    expect(document.documentElement.style.getPropertyValue('--brand-primary')).toBe('')
    expect(document.documentElement.style.getPropertyValue('--brand-header-text')).toBe('')
  })

  it('derives a legible header text colour when bg is set but text is not', () => {
    applyBrandVars({ header_bg: '#000000' })
    expect(document.documentElement.style.getPropertyValue('--brand-header-text')).toBe('#ffffff')
  })

  it('derives dark header text on a light header bg', () => {
    applyBrandVars({ header_bg: '#ffffff' })
    expect(document.documentElement.style.getPropertyValue('--brand-header-text')).toBe('#1A1D29')
  })

  it('an explicit header_text always wins over the derived colour', () => {
    applyBrandVars({ header_bg: '#000000', header_text: '#ff0000' })
    expect(document.documentElement.style.getPropertyValue('--brand-header-text')).toBe('#ff0000')
  })
})
