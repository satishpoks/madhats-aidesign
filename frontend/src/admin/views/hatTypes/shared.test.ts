import { describe, it, expect } from 'vitest'
import { slugify, angleCount, allAngles, hatStatus, VIEWS } from './shared'

describe('hat-type shared helpers', () => {
  it('slugifies a display name', () => {
    expect(slugify('Trucker Cap!')).toBe('trucker-cap')
    expect(slugify('  5-Panel  ')).toBe('5-panel')
  })

  it('counts present angles', () => {
    expect(angleCount({ blank_view_images: { front: 'a', back: 'b' } })).toBe(2)
    expect(allAngles({ blank_view_images: { front: 'a', back: 'b', left: 'c', right: 'd' } })).toBe(true)
  })

  it('derives status from angles + active flag', () => {
    expect(hatStatus({ blank_view_images: { front: 'a' }, active: false })).toBe('needs_images')
    const full = { front: 'a', back: 'b', left: 'c', right: 'd' }
    expect(hatStatus({ blank_view_images: full, active: false })).toBe('draft')
    expect(hatStatus({ blank_view_images: full, active: true })).toBe('active')
    expect(VIEWS).toHaveLength(4)
  })
})
