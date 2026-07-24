import { describe, expect, it, vi } from 'vitest'
import { downloadImage } from './downloadImage'

describe('downloadImage', () => {
  it('rejects when the fetch response is not ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 404 } as Response),
    )
    await expect(downloadImage('x', 'y')).rejects.toThrow('Download failed (404)')
    vi.unstubAllGlobals()
  })
})
