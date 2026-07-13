import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@imgly/background-removal', () => ({
  removeBackground: vi.fn(async () => new Blob(['x'], { type: 'image/png' })),
}))
vi.mock('./api', () => ({
  uploadLogo: vi.fn(async () => ({ asset_url: 'stored/nobg.png', asset_hash: 'h' })),
}))

import { toggleBackground } from './bgRemove'
import { uploadLogo } from './api'

beforeEach(() => vi.clearAllMocks())

describe('toggleBackground', () => {
  it('ON: mattes, uploads the transparent PNG, records the original url', async () => {
    const el = { id: '1', type: 'image', assetUrl: 'orig.png' } as never
    const patch = await toggleBackground('s1', el, true)
    expect(uploadLogo).toHaveBeenCalledTimes(1)
    expect(patch).toEqual({ assetUrl: 'stored/nobg.png', removeBg: true, originalAssetUrl: 'orig.png' })
  })

  it('OFF: re-uploads the original image and clears removeBg', async () => {
    globalThis.fetch = vi.fn(async () => ({ blob: async () => new Blob(['y'], { type: 'image/png' }) })) as never
    const el = { id: '1', type: 'image', assetUrl: 'nobg.png', originalAssetUrl: 'orig.png' } as never
    const patch = await toggleBackground('s1', el, false)
    expect(globalThis.fetch).toHaveBeenCalledWith('orig.png')
    expect(uploadLogo).toHaveBeenCalledTimes(1)
    expect(patch).toEqual({ assetUrl: 'stored/nobg.png', removeBg: false })
  })
})
