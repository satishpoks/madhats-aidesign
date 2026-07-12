import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { HatTypeEditView } from './HatTypeEditView'
import * as api from '../adminApi'

vi.mock('../adminApi')

const STORE = {
  id: 's1', slug: 'madhats', name: 'MadHats',
  public_key: 'mh_pk_test', shopify_domain: null, status: 'active',
}

function hat(overrides: Partial<api.HatType> = {}): api.HatType {
  return {
    id: 'h1', store_id: 's1', slug: '5p', name: '5-Panel', style: 'trucker', description: '',
    blank_view_images: { front: 'a', back: 'b', left: 'c', right: 'd' },
    view_images: { front: 'u', back: 'u', left: 'u', right: 'u' },
    colours: [{ name: 'Black', hex: '#000000' }],
    placement_zones: [], decoration_types: [], pricing_slabs: [], active: true,
    ...overrides,
  }
}

function renderEdit() {
  return render(
    <MemoryRouter initialEntries={['/admin/hat-types/h1?store=s1']}>
      <Routes>
        <Route path="/admin/hat-types/:id" element={<HatTypeEditView />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('HatTypeEditView', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.listStores).mockResolvedValue([STORE])
  })

  it('loads the record and populates fields', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat()])
    renderEdit()
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('5-Panel'))
  })

  it('saves the basics section independently', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat()])
    vi.mocked(api.updateHatType).mockResolvedValue(hat({ name: 'Six Panel' }))
    renderEdit()
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('5-Panel'))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Six Panel' } })
    fireEvent.click(screen.getByRole('button', { name: /save basics/i }))
    await waitFor(() =>
      expect(api.updateHatType).toHaveBeenCalledWith(
        'h1',
        { name: 'Six Panel', style: 'trucker', description: '' },
        'mh_pk_test',
      ),
    )
  })

  it('disables the active toggle until all four angles exist', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat({ active: false, blank_view_images: { front: 'a' } })])
    renderEdit()
    await waitFor(() => expect(screen.getByRole('checkbox', { name: /active/i })).toBeInTheDocument())
    expect(screen.getByRole('checkbox', { name: /active/i })).toBeDisabled()
  })

  it('preserves locally-known thumbnails after a basics save that omits view_images', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat()])
    // Backend PATCH response does not include view_images (defaults to {}).
    vi.mocked(api.updateHatType).mockResolvedValue(
      hat({ name: 'Six Panel', view_images: {} }),
    )
    renderEdit()
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('5-Panel'))
    expect(screen.getByAltText('front')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Six Panel' } })
    fireEvent.click(screen.getByRole('button', { name: /save basics/i }))

    await waitFor(() => expect(api.updateHatType).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('Six Panel'))
    expect(screen.getByAltText('front')).toBeInTheDocument()
  })

  it('shows a missing-store error instead of a perpetual "Loading…" for an unknown ?store=', async () => {
    render(
      <MemoryRouter initialEntries={['/admin/hat-types/h1?store=bogus']}>
        <Routes>
          <Route path="/admin/hat-types/:id" element={<HatTypeEditView />} />
        </Routes>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText(/unknown or missing store/i)).toBeInTheDocument())
    expect(screen.queryByText(/^loading…$/i)).not.toBeInTheDocument()
  })
})
