import { describe, it, expect } from 'vitest'
import { removeBgValue } from '../admin/views/SessionDetailView'

describe('remove-background brief row', () => {
  it('reports Yes when any canvas element is flagged', () => {
    expect(removeBgValue({ elements: [
      { type: 'logo', remove_bg: false },
      { type: 'logo', remove_bg: true },
    ] })).toBe(true)
  })

  it('reports No when canvas elements exist but none are flagged', () => {
    expect(removeBgValue({ elements: [{ type: 'logo', remove_bg: false }] })).toBe(false)
  })

  it('falls back to the v1 top-level flag when there are no elements', () => {
    expect(removeBgValue({ remove_bg: true })).toBe(true)
  })

  it('is undefined when neither source says anything', () => {
    expect(removeBgValue({})).toBeUndefined()
  })
})
