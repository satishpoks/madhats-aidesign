import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../admin/adminApi', () => ({
  promptPreview: vi.fn(),
  backfillDeliveries: vi.fn(),
}))

import { promptPreview, backfillDeliveries } from '../admin/adminApi'
import { OpsView } from '../admin/views/OpsView'

beforeEach(() => {
  vi.mocked(promptPreview).mockReset()
  vi.mocked(backfillDeliveries).mockReset()
})

describe('OpsView prompt preview', () => {
  it('fetches and displays the prompt', async () => {
    vi.mocked(promptPreview).mockResolvedValue({
      session_id: 'sess-1', tier: 'preview', provider: 'GeminiFlash', model: 'gemini-2.5-flash-image',
      reference_image_url: 'https://img/ref.png', has_uploaded_asset: false, prompt: 'DO THIS AND THAT',
    })
    render(<OpsView />)
    fireEvent.change(screen.getByLabelText(/session id/i), { target: { value: 'sess-1' } })
    fireEvent.click(screen.getByRole('button', { name: /preview prompt/i }))
    await waitFor(() => expect(screen.getByText('DO THIS AND THAT')).toBeInTheDocument())
    expect(promptPreview).toHaveBeenCalledWith('sess-1', 'preview')
  })
})

describe('OpsView delivery backfill', () => {
  it('runs the backfill and shows the result', async () => {
    vi.mocked(backfillDeliveries).mockResolvedValue({ retried: 3, sent: 2 })
    render(<OpsView />)
    fireEvent.click(screen.getByRole('button', { name: /run backfill/i }))
    await waitFor(() => expect(backfillDeliveries).toHaveBeenCalledWith(100, 72))
    await waitFor(() => expect(screen.getByText(/"retried": 3/)).toBeInTheDocument())
  })
})
