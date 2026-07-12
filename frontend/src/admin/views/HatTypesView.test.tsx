import { render, screen, waitFor } from '@testing-library/react'
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
    colours: [],
    placement_zones: [],
    decoration_types: [],
    pricing_slabs: [],
    active: false,
    ...overrides,
  }
}

describe('HatTypesView', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.listStores).mockResolvedValue([STORE])
  })

  it('lists hat types for the selected store using its store key', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat()])
    render(<HatTypesView />)
    await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
    expect(api.listHatTypes).toHaveBeenCalledWith('mh_pk_test')
  })

  it('does not call listHatTypes until a store is selected', () => {
    vi.mocked(api.listStores).mockReturnValue(new Promise(() => {}))
    render(<HatTypesView />)
    expect(api.listHatTypes).not.toHaveBeenCalled()
  })

  it('disables the active toggle when angle images are incomplete', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([
      hat({ blank_view_images: { front: 'a', back: 'b' } }),
    ])
    render(<HatTypesView />)
    await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
    expect(screen.getByRole('checkbox', { name: /active/i })).toBeDisabled()
  })

  it('enables the active toggle once all four angles are present', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([
      hat({ blank_view_images: { front: 'a', back: 'b', left: 'c', right: 'd' } }),
    ])
    render(<HatTypesView />)
    await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
    expect(screen.getByRole('checkbox', { name: /active/i })).not.toBeDisabled()
  })
})
