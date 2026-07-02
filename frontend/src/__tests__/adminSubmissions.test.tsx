import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

vi.mock('../admin/adminApi', () => ({
  listSubmissions: vi.fn(),
  updateSubmission: vi.fn(),
}))

import { listSubmissions, updateSubmission } from '../admin/adminApi'
import { SubmissionsView } from '../admin/views/SubmissionsView'
import { SubmissionDetailView } from '../admin/views/SubmissionDetailView'

const sub = {
  id: 'sub-1',
  session_id: 'sess-1',
  product_ref: { name: 'Classic Cap' },
  final_image_urls: ['https://img/1.png'],
  source_ref: null,
  customer: { name: 'Jane' },
  review_status: 'pending',
  reviewer_notes: null,
  created_at: '2026-07-01T00:00:00Z',
  decided_at: null,
}

beforeEach(() => {
  vi.mocked(listSubmissions).mockReset()
  vi.mocked(updateSubmission).mockReset()
})

describe('SubmissionsView', () => {
  it('lists submissions from the API', async () => {
    vi.mocked(listSubmissions).mockResolvedValue([sub])
    render(
      <MemoryRouter>
        <SubmissionsView />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('Classic Cap')).toBeInTheDocument())
  })

  it('shows an error banner when the fetch fails', async () => {
    vi.mocked(listSubmissions).mockRejectedValue(new Error('nope'))
    render(
      <MemoryRouter>
        <SubmissionsView />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})

describe('SubmissionDetailView', () => {
  it('approves with reviewer notes', async () => {
    vi.mocked(listSubmissions).mockResolvedValue([sub])
    vi.mocked(updateSubmission).mockResolvedValue({ updated: true })
    render(
      <MemoryRouter initialEntries={['/admin/submissions/sub-1']}>
        <Routes>
          <Route path="/admin/submissions/:id" element={<SubmissionDetailView />} />
          <Route path="/admin/submissions" element={<div>list</div>} />
        </Routes>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText(/Jane/)).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/reviewer notes/i), { target: { value: 'looks good' } })
    fireEvent.click(screen.getByRole('button', { name: /approve/i }))
    await waitFor(() =>
      expect(updateSubmission).toHaveBeenCalledWith('sub-1', {
        review_status: 'approved',
        reviewer_notes: 'looks good',
      }),
    )
  })
})
