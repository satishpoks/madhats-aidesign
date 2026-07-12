import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useGenerationStore } from './generationStore'
import * as api from '../lib/api'

vi.mock('../lib/api')

describe('generationStore designs', () => {
  beforeEach(() => {
    useGenerationStore.getState().reset()
    vi.resetAllMocks()
  })

  it('appends the completed design to designs[]', async () => {
    vi.mocked(api.generatePreview).mockResolvedValue({ job_id: 'j1' })
    vi.mocked(api.generationStatus).mockResolvedValue({
      status: 'complete',
      image_url: 'clean.png',
      watermarked_url: 'wm.png',
    } as never)
    await useGenerationStore.getState().startGeneration('s1')
    expect(useGenerationStore.getState().designs).toEqual(['wm.png'])
  })

  it('appends every rendered view (front→back→left→right) for a multi-view design', async () => {
    vi.mocked(api.generatePreview).mockResolvedValue({ job_id: 'j1' })
    vi.mocked(api.generationStatus).mockResolvedValue({
      status: 'complete',
      image_url: 'front-clean.png',
      watermarked_url: 'front-wm.png',
      view_images: { front: 'front-wm.png', back: 'back-wm.png' },
    } as never)
    await useGenerationStore.getState().startGeneration('s1')
    expect(useGenerationStore.getState().designs).toEqual(['front-wm.png', 'back-wm.png'])
    expect(useGenerationStore.getState().previewUrl).toBe('front-wm.png')
  })

  it('startRegeneration appends a second design', async () => {
    const api = await import('../lib/api')
    ;(api.regenerate as unknown as ReturnType<typeof vi.fn>) = vi.fn().mockResolvedValue({ job_id: 'j2' })
    vi.mocked(api.generationStatus).mockResolvedValue({
      status: 'complete', image_url: 'c2.png', watermarked_url: 'wm2.png',
    } as never)
    useGenerationStore.setState({ designs: ['wm1.png'] })
    await useGenerationStore.getState().startRegeneration('s1')
    expect(useGenerationStore.getState().designs).toEqual(['wm1.png', 'wm2.png'])
  })
})
