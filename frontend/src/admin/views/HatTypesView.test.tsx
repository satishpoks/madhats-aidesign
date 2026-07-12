import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { HatTypesView } from './HatTypesView'
import * as api from '../adminApi'

vi.mock('../adminApi')

const STORE = {
  id: 's1',
  slug: 'madhats',
  name: 'MadHats',
  public_key: 'mh_pk_test',
  shopify_domain: null,
  status: 'active',
}

function hat(overrides: Partial<api.HatType> = {}): api.HatType {
  return {
    id: 'h1',
    store_id: 's1',
    slug: '5p',
    name: '5-Panel',
    style: '',
    description: null,
    blank_view_images: {},
    view_images: {},
    colours: [],
    placement_zones: [],
    decoration_types: [],
    pricing_slabs: [],
    active: false,
    ...overrides,
  }
}

function renderView() {
  return render(
    <MemoryRouter initialEntries={['/admin/hat-types']}>
      <HatTypesView />
    </MemoryRouter>,
  )
}

describe('HatTypesView (list)', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.listStores).mockResolvedValue([STORE])
  })

  it('lists hat types for the selected store using its store key', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat()])
    renderView()
    await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
    expect(api.listHatTypes).toHaveBeenCalledWith('mh_pk_test')
  })

  it('shows a "Needs images" status when angles are incomplete', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat({ blank_view_images: { front: 'a' } })])
    renderView()
    await waitFor(() => expect(screen.getByText(/needs images/i)).toBeInTheDocument())
  })

  it('shows "Active" for a live, fully-angled hat type', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([
      hat({ active: true, blank_view_images: { front: 'a', back: 'b', left: 'c', right: 'd' } }),
    ])
    renderView()
    await waitFor(() => expect(screen.getByText('Active')).toBeInTheDocument())
  })

  it('filters the list by search text', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat(), hat({ id: 'h2', name: 'Beanie' })])
    renderView()
    await waitFor(() => expect(screen.getByText('Beanie')).toBeInTheDocument())
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'bean' } })
    expect(screen.queryByText('5-Panel')).not.toBeInTheDocument()
    expect(screen.getByText('Beanie')).toBeInTheDocument()
  })

  it('links the Add button to the create wizard for the selected store', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([])
    renderView()
    await waitFor(() => expect(screen.getByRole('link', { name: /add hat type/i })).toBeInTheDocument())
    expect(screen.getByRole('link', { name: /add hat type/i })).toHaveAttribute(
      'href',
      '/admin/hat-types/new?store=s1',
    )
  })

  it('deletes after inline confirm', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat()])
    vi.mocked(api.deleteHatType).mockResolvedValue({ deleted: true })
    renderView()
    await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /delete/i }))
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))
    await waitFor(() => expect(api.deleteHatType).toHaveBeenCalledWith('h1', 'mh_pk_test'))
  })
})
