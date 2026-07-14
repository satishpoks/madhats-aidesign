import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SettingsView } from './SettingsView'
import * as api from '../adminApi'

vi.mock('../adminApi')

describe('SettingsView', () => {
  beforeEach(() => vi.resetAllMocks())

  it('loads and displays current settings', async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      regen_edits_per_session: 3,
      designs_per_customer_per_day: 2,
      faq_knowledge: 'Turnaround is 2 weeks.',
      watermark_text: 'MADHATS PREVIEW',
    })
    render(<SettingsView />)
    await waitFor(() =>
      expect(screen.getByLabelText(/edits per session/i)).toHaveValue(3),
    )
    expect(screen.getByLabelText(/designs per customer per day/i)).toHaveValue(2)
    expect(screen.getByLabelText(/faq/i)).toHaveValue('Turnaround is 2 weeks.')
    expect(screen.getByLabelText(/watermark text/i)).toHaveValue('MADHATS PREVIEW')
  })
})
