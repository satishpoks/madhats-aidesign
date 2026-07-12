import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AngleUploader } from './AngleUploader'
import * as api from '../../adminApi'

vi.mock('../../adminApi')

describe('AngleUploader', () => {
  beforeEach(() => vi.resetAllMocks())

  it('renders a thumbnail when a view image exists', () => {
    render(
      <AngleUploader hatId="h1" storeKey="k" viewImages={{ front: 'http://img/front.png' }} onUploaded={vi.fn()} />,
    )
    expect(screen.getByAltText('front')).toHaveAttribute('src', 'http://img/front.png')
  })

  it('uploads a file and reports the returned url', async () => {
    vi.mocked(api.uploadHatAngle).mockResolvedValue({
      blank_view_images: { front: 'p/front.png' },
      view_images: { front: 'http://img/front.png' },
    })
    const onUploaded = vi.fn()
    render(<AngleUploader hatId="h1" storeKey="k" viewImages={{}} onUploaded={onUploaded} />)
    const file = new File(['x'], 'front.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('Upload front'), { target: { files: [file] } })
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith('front', 'http://img/front.png'))
    expect(api.uploadHatAngle).toHaveBeenCalledWith('h1', 'front', file, 'k')
  })

  it('surfaces an error when the response has no url for the view', async () => {
    vi.mocked(api.uploadHatAngle).mockResolvedValue({
      blank_view_images: {},
      view_images: {},
    })
    const onUploaded = vi.fn()
    render(<AngleUploader hatId="h1" storeKey="k" viewImages={{}} onUploaded={onUploaded} />)
    const file = new File(['x'], 'front.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('Upload front'), { target: { files: [file] } })
    expect(await screen.findByText(/no image url/i)).toBeInTheDocument()
    expect(onUploaded).not.toHaveBeenCalled()
  })
})
