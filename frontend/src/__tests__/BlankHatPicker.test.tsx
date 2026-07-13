import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BlankHatPicker } from '../components/BlankHatPicker'
import * as api from '../lib/api'
import { useSessionStore } from '../store/sessionStore'
import { it, expect, vi, beforeEach } from 'vitest'

beforeEach(() => {
  useSessionStore.setState({
    sessionId: null,
    shareToken: null,
    state: null,
    productRef: null,
    entryContext: null,
    view: 'picker',
  })
})

it('lists hat types from the API', async () => {
  vi.spyOn(api, 'listHatTypes').mockResolvedValue([
    { id: 'h1', slug: '5p', name: '5-Panel', style: '', view_images: { front: 'u' },
      colours: [{ name: 'Black', hex: '#000000' }], placement_zones: [], decoration_types: [] },
  ])
  render(<BlankHatPicker />)
  await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
})

it('shows a loading state before hats resolve, then an empty state if none come back', async () => {
  let resolveHats: (value: api.HatType[]) => void = () => {}
  vi.spyOn(api, 'listHatTypes').mockReturnValue(
    new Promise<api.HatType[]>(resolve => { resolveHats = resolve })
  )
  render(<BlankHatPicker />)
  expect(screen.getByText('Loading hats…')).toBeInTheDocument()
  expect(screen.queryByText('No blank hats available yet.')).not.toBeInTheDocument()

  resolveHats([])
  await waitFor(() => expect(screen.getByText('No blank hats available yet.')).toBeInTheDocument())
})

it('starts a blank session with the selected hat (colour is chosen later in chat)', async () => {
  vi.spyOn(api, 'listHatTypes').mockResolvedValue([
    { id: 'h1', slug: '5p', name: '5-Panel', style: '', view_images: { front: 'u' },
      colours: [{ name: 'Black', hex: '#000000' }, { name: 'Navy', hex: '#001f3f' }],
      placement_zones: [], decoration_types: [] },
  ])
  const startCanvasBlankSession = vi.fn().mockResolvedValue(undefined)
  useSessionStore.setState({ startCanvasBlankSession })

  const user = userEvent.setup()
  render(<BlankHatPicker />)

  await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
  await user.click(screen.getByText('5-Panel'))

  // The entry screen no longer has a colour picker — colour is asked in chat.
  expect(screen.queryByTitle('Navy')).not.toBeInTheDocument()

  await user.click(screen.getByText('Start designing'))

  // Passes just the hat type (no colour); the store populates the left-pane
  // productRef from its blank angle images + name.
  await waitFor(() =>
    expect(startCanvasBlankSession).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'h1', name: '5-Panel', view_images: { front: 'u' } }),
    ),
  )
})

it('shows an error message if starting the session fails', async () => {
  vi.spyOn(api, 'listHatTypes').mockResolvedValue([
    { id: 'h1', slug: '5p', name: '5-Panel', style: '', view_images: { front: 'u' },
      colours: [{ name: 'Black', hex: '#000000' }], placement_zones: [], decoration_types: [] },
  ])
  const startCanvasBlankSession = vi.fn().mockRejectedValue(new Error('network down'))
  useSessionStore.setState({ startCanvasBlankSession })

  const user = userEvent.setup()
  render(<BlankHatPicker />)

  await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
  await user.click(screen.getByText('5-Panel'))
  await user.click(screen.getByText('Start designing'))

  await waitFor(() => expect(screen.getByText('network down')).toBeInTheDocument())
})
