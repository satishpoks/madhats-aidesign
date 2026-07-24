import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { SessionDetailView } from './SessionDetailView'
import * as api from '../adminApi'

vi.mock('../adminApi', async (orig) => {
  const actual = await orig<typeof api>()
  return { ...actual, getSessionDetail: vi.fn() }
})

const baseDetail = {
  id: 's1', store_id: null, share_token: null, state: 'complete', status: null,
  channel: 'web', entry_path: null, product: 'Cap', product_ref: null,
  reference_image_url: null, view_images: {}, collected: {}, created_at: null,
  messages: [], generations: [], leads: [],
  canvas_design: {},
  canvas_faces: [{
    face: 'front', preview_url: 'http://api/media/p', layout_url: 'http://api/media/l',
    elements: [
      { kind: 'image', url: 'http://api/media/i', download_name: 'front-upload-1.png', text: 'uploaded logo/artwork' },
      { kind: 'text', text: 'text reading "SATISH", in white, Arial font' },
    ],
  }],
}

function renderAt() {
  return render(
    <MemoryRouter initialEntries={['/admin/sessions/s1']}>
      <Routes><Route path="/admin/sessions/:id" element={<SessionDetailView />} /></Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => { vi.mocked(api.getSessionDetail).mockReset() })

describe('SessionDetailView customer design section', () => {
  it('renders the customer design section with images and element text', async () => {
    vi.mocked(api.getSessionDetail).mockResolvedValue(baseDetail as unknown as api.SessionDetail)
    renderAt()
    expect(await screen.findByText(/Customer's design/i)).toBeInTheDocument()
    expect(await screen.findByText(/SATISH/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /download/i }).length).toBeGreaterThan(0)
  })

  it('omits the section when there are no canvas faces', async () => {
    vi.mocked(api.getSessionDetail).mockResolvedValue({ ...baseDetail, canvas_faces: [] } as unknown as api.SessionDetail)
    renderAt()
    await screen.findAllByText('Cap')
    expect(screen.queryByText(/Customer's design/i)).not.toBeInTheDocument()
  })
})
