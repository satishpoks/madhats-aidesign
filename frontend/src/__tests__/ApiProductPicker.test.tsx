import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { Product } from '../lib/types'

// vi.mock factory is hoisted to the top of the file by Vitest, so it must not
// reference variables defined in module scope. Use inline literals here.
vi.mock('../lib/api', () => ({
  fetchProducts: vi.fn().mockResolvedValue({
    items: [
      {
        id: 'prod-1',
        name: 'Classic Snapback',
        colour: 'Black',
        style: 'snapback',
        reference_image_url: 'https://example.com/cap.jpg',
        view_images: {},
        placement_zones: ['front'],
        decoration_types: ['embroidery'],
      },
    ],
    total: 1,
    limit: 24,
    offset: 0,
  }),
  createSession: vi.fn().mockResolvedValue({
    session_id: 'sess-1',
    share_token: 'tok-1',
    state: 'collecting_brief',
  }),
  fetchProduct: vi.fn(),
}))

// Static imports come after vi.mock — Vitest ensures the mock is in place first.
import { createSession, fetchProducts } from '../lib/api'
import { useSessionStore } from '../store/sessionStore'
import { ApiProductPicker } from '../components/ApiProductPicker'

const mockProduct: Product = {
  id: 'prod-1',
  name: 'Classic Snapback',
  colour: 'Black',
  style: 'snapback',
  reference_image_url: 'https://example.com/cap.jpg',
  view_images: {},
  placement_zones: ['front'],
  decoration_types: ['embroidery'],
}

beforeEach(() => {
  // Restore default mock behaviour before each test
  vi.mocked(fetchProducts).mockResolvedValue({
    items: [mockProduct],
    total: 1,
    limit: 24,
    offset: 0,
  })
  vi.mocked(createSession).mockResolvedValue({
    session_id: 'sess-1',
    share_token: 'tok-1',
    state: 'collecting_brief',
  })
  // Reset Zustand store to initial state
  useSessionStore.setState({
    sessionId: null,
    shareToken: null,
    state: null,
    productRef: null,
    entryContext: null,
    view: 'picker',
  })
})

describe('ApiProductPicker handleSelect error handling', () => {
  it('shows an inline error when session creation fails', async () => {
    vi.mocked(createSession).mockRejectedValueOnce(new Error('Network error'))

    render(<ApiProductPicker />)

    // Wait for the product list to load, then click a product
    const productButton = await screen.findByText('Classic Snapback')
    fireEvent.click(productButton)

    // Inline alert should appear with the error message
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
      expect(screen.getByText('Network error')).toBeInTheDocument()
    })
  })

  it('the inline error is dismissible', async () => {
    vi.mocked(createSession).mockRejectedValueOnce(new Error('Network error'))

    render(<ApiProductPicker />)
    const productButton = await screen.findByText('Classic Snapback')
    fireEvent.click(productButton)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    // Click the Dismiss button (matched by aria-label)
    fireEvent.click(screen.getByRole('button', { name: /dismiss error/i }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('clears a previous error immediately when a new product is clicked', async () => {
    vi.mocked(createSession).mockRejectedValueOnce(new Error('First error'))

    render(<ApiProductPicker />)
    const productButton = await screen.findByText('Classic Snapback')

    // First click fails — error appears
    fireEvent.click(productButton)
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    // Second click: setSelectError(null) fires first, so error clears immediately
    vi.mocked(createSession).mockResolvedValueOnce({
      session_id: 'sess-1',
      share_token: 'tok-1',
      state: 'collecting_brief',
    })
    fireEvent.click(productButton)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('does not show an error banner on a successful selection', async () => {
    // createSession succeeds (default mock)
    render(<ApiProductPicker />)
    const productButton = await screen.findByText('Classic Snapback')
    fireEvent.click(productButton)

    await waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
  })
})
