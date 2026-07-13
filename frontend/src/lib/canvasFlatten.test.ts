import { describe, it, expect } from 'vitest'
import { dataUrlToFile } from './canvasFlatten'

// 1x1 transparent PNG
const PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='

describe('dataUrlToFile', () => {
  it('decodes a data URL into a PNG File', () => {
    const f = dataUrlToFile(PNG, 'front.png')
    expect(f).toBeInstanceOf(File)
    expect(f.type).toBe('image/png')
    expect(f.name).toBe('front.png')
    expect(f.size).toBeGreaterThan(0)
  })
})
