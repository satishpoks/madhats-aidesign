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
})
