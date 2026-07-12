import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { HatTypeWizard } from './HatTypeWizard'
import * as api from '../adminApi'

vi.mock('../adminApi')

const STORE = {
  id: 's1', slug: 'madhats', name: 'MadHats',
  public_key: 'mh_pk_test', shopify_domain: null, status: 'active',
}

function fullHat(overrides: Partial<api.HatType> = {}): api.HatType {
  return {
    id: 'h1', store_id: 's1', slug: 'trucker-cap', name: 'Trucker Cap', style: '', description: '',
    blank_view_images: { front: 'a', back: 'b', left: 'c', right: 'd' },
    view_images: { front: 'u', back: 'u', left: 'u', right: 'u' },
    colours: [], placement_zones: [], decoration_types: [], pricing_slabs: [], active: false,
    ...overrides,
  }
}

function renderWizard() {
  return render(
    <MemoryRouter initialEntries={['/admin/hat-types/new?store=s1']}>
      <Routes>
        <Route path="/admin/hat-types/new" element={<HatTypeWizard />} />
        <Route path="/admin/hat-types" element={<div>LIST</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('HatTypeWizard', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.listStores).mockResolvedValue([STORE])
    vi.mocked(api.updateHatType).mockResolvedValue(fullHat({ active: true }))
  })

  it('creates a draft with a slugified slug when leaving Basics', async () => {
    vi.mocked(api.createHatType).mockResolvedValue(fullHat())
    renderWizard()
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Trucker Cap' } })
    fireEvent.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() =>
      expect(api.createHatType).toHaveBeenCalledWith(
        { name: 'Trucker Cap', slug: 'trucker-cap', style: '', description: '' },
        'mh_pk_test',
      ),
    )
  })

  it('walks to review and activates, then returns to the list', async () => {
    vi.mocked(api.createHatType).mockResolvedValue(fullHat())
    renderWizard()
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Trucker Cap' } })
    fireEvent.click(screen.getByRole('button', { name: /next/i })) // Basics -> Angles
    await waitFor(() => expect(screen.getByText(/step 2 of 5/i)).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /next/i })) // Angles -> Colourways
    await waitFor(() => expect(screen.getByText('Colourways')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /next/i })) // Colourways -> Zones
    await waitFor(() => expect(screen.getByText('Zones & decoration')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /next/i })) // Zones -> Review
    await waitFor(() => expect(screen.getByRole('button', { name: /activate/i })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))
    await waitFor(() => expect(api.updateHatType).toHaveBeenCalledWith('h1', { active: true }, 'mh_pk_test'))
    await waitFor(() => expect(screen.getByText('LIST')).toBeInTheDocument())
  })

  it('persists edited basics when returning to step 1 (no double-create)', async () => {
    vi.mocked(api.createHatType).mockResolvedValue(fullHat())
    vi.mocked(api.updateHatType).mockResolvedValue(fullHat({ name: 'Six Panel' }))
    renderWizard()
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Trucker Cap' } })
    fireEvent.click(screen.getByRole('button', { name: /next/i })) // Basics -> Angles
    await waitFor(() => expect(screen.getByText(/step 2 of 5/i)).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /back/i })) // Angles -> Basics
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Six Panel' } })
    fireEvent.click(screen.getByRole('button', { name: /next/i })) // Basics -> Angles again
    await waitFor(() =>
      expect(api.updateHatType).toHaveBeenCalledWith(
        'h1',
        { name: 'Six Panel', style: '', description: '' },
        'mh_pk_test',
      ),
    )
    expect(api.createHatType).toHaveBeenCalledTimes(1)
  })
})
