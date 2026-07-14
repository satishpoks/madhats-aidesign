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
  })
})
