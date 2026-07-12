import { render, screen, waitFor } from '@testing-library/react'
import { BlankHatPicker } from '../components/BlankHatPicker'
import * as api from '../lib/api'
import { it, expect, vi } from 'vitest'

it('lists hat types from the API', async () => {
  vi.spyOn(api, 'listHatTypes').mockResolvedValue([
    { id: 'h1', slug: '5p', name: '5-Panel', style: '', view_images: { front: 'u' },
      colours: [{ name: 'Black', hex: '#000000' }], placement_zones: [], decoration_types: [] },
  ])
  render(<BlankHatPicker />)
  await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
})
