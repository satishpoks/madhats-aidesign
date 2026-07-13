import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Mock both heavy children so the screen renders without react-konva or store wiring.
vi.mock('../components/DesignStudio/Surface', () => ({
  DesignStudioSurface: () => <div data-testid="surface" />,
}))
vi.mock('../components/CustomiseStudio/ChatColumn', () => ({
  ChatColumn: () => <div data-testid="chat-column" />,
}))

import { useSessionStore } from '../store/sessionStore'
import { CustomiseStudio } from '../components/CustomiseStudio'

beforeEach(() => {
  useSessionStore.setState({
    sessionId: 'sess-1', shareToken: 't', state: 'greeting',
    productRef: {
      id: 'p1', name: 'Classic Snapback', colour: 'Black', style: 'snapback',
      reference_image_url: 'https://example.com/cap.jpg', view_images: {},
    },
    entryContext: null, view: 'canvas',
  })
})

describe('CustomiseStudio', () => {
  it('renders the canvas surface and the chat column side by side', () => {
    render(<CustomiseStudio />)
    expect(screen.getByTestId('surface')).toBeInTheDocument()
    expect(screen.getByTestId('chat-column')).toBeInTheDocument()
  })

  it('shows the shared header with the product breadcrumb', () => {
    render(<CustomiseStudio />)
    expect(screen.getByText('MAD HATS')).toBeInTheDocument()
    expect(screen.getByText(/Classic Snapback/)).toBeInTheDocument()
  })
})
