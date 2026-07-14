import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { OpsView } from './OpsView'
import * as api from '../adminApi'

vi.mock('../adminApi')

const JOBS: api.GenerationJobs = {
  stuck_minutes: 8,
  summary: { pending: 2, stalled: 1, failed: 1, complete: 3 },
  items: [
    {
      job_id: 'job-stuck', session_id: 'sess-1', tier: 'preview',
      status: 'pending', model: 'pending', error: null, attempts: 0,
      created_at: '2026-07-14T02:00:00Z', age_seconds: 1200, stalled: true,
    },
    {
      job_id: 'job-done', session_id: 'sess-2', tier: 'preview',
      status: 'complete', model: 'gemini-3-pro-image', error: null, attempts: 1,
      created_at: '2026-07-14T02:10:00Z', age_seconds: 60, stalled: false,
    },
  ],
}

describe('OpsView — Generation jobs', () => {
  beforeEach(() => vi.resetAllMocks())

  it('renders the summary tiles and job rows', async () => {
    vi.mocked(api.listGenerations).mockResolvedValue(JOBS)
    render(<OpsView />)

    // Stalled tile shows the count, and the stalled row is marked.
    await waitFor(() => expect(screen.getByText('Stalled')).toBeInTheDocument())
    expect(screen.getByText('gemini-3-pro-image')).toBeInTheDocument()
    expect(screen.getByText('stalled')).toBeInTheDocument()
  })

  it('reaps stuck jobs and refetches on confirm', async () => {
    vi.mocked(api.listGenerations).mockResolvedValue(JOBS)
    vi.mocked(api.reapStuck).mockResolvedValue({ reaped: 1, retried: 1, gave_up: 0 })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<OpsView />)
    await waitFor(() => expect(screen.getByText('gemini-3-pro-image')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /reap stuck now/i }))

    await waitFor(() => expect(vi.mocked(api.reapStuck)).toHaveBeenCalledTimes(1))
    // list is fetched again after the reap (initial mount + post-reap)
    await waitFor(() => expect(vi.mocked(api.listGenerations).mock.calls.length).toBeGreaterThanOrEqual(2))
  })
})
