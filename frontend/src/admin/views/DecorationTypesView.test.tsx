import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi, test, expect, beforeEach } from 'vitest'
import { DecorationTypesView } from './DecorationTypesView'
import * as adminApi from '../adminApi'
import * as shared from './hatTypes/shared'

beforeEach(() => {
  vi.spyOn(shared, 'useStores').mockReturnValue({
    stores: [{ id: 's1', name: 'MadHats', public_key: 'mh_pk' } as never], error: null,
  } as never)
  vi.spyOn(adminApi, 'listDecorationTypes').mockResolvedValue([
    { id: 'd1', name: 'Embroidery', active: true, sort_order: 0 },
  ])
})

test('lists decoration types for the selected store', async () => {
  render(
    <MemoryRouter initialEntries={['/admin/decoration-types?store=s1']}>
      <DecorationTypesView />
    </MemoryRouter>,
  )
  await waitFor(() => expect(screen.getByText('Embroidery')).toBeInTheDocument())
})
