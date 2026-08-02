import { describe, expect, it, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ColumnHeader } from '../components/CustomiseStudio/ColumnHeader'

vi.mock('../components/DesignStudio/Surface', () => ({
  DesignStudioSurface: () => <div data-testid="surface" />,
}))
vi.mock('../components/CustomiseStudio/ChatColumn', () => ({
  ChatColumn: () => <div data-testid="chat-column" />,
}))

import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import { CustomiseStudio } from '../components/CustomiseStudio'

describe('ColumnHeader tone', () => {
  it('fills with the store primary colour for the assistant half', () => {
    render(<ColumnHeader name="Ricardo" instruction="Your turn — answer here"
                         active tone="primary" />)
    expect(screen.getByRole('status').className).toContain('bg-accent')
  })

  it('fills with the customer bubble colour for the customer half', () => {
    render(<ColumnHeader name="Your design" instruction="Your turn — design here"
                         active tone="customer" />)
    expect(screen.getByRole('status').className).toContain('bg-chatUserBubble')
  })

  it('uses neither tone while resting', () => {
    const { container } = render(
      <ColumnHeader name="Ricardo" instruction="x" active={false} tone="primary" />)
    const el = container.firstElementChild as HTMLElement
    expect(el.className).not.toContain('bg-accent')
    expect(el.className).toContain('bg-surfaceAlt')
  })
})

describe('CustomiseStudio assigns each half its own tone', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
    useSessionStore.setState({
      sessionId: 'sess-1', shareToken: 't', state: 'greeting',
      productRef: {
        id: 'p1', name: 'Classic Snapback', colour: 'Black', style: 'snapback',
        reference_image_url: 'https://example.com/cap.jpg', view_images: {},
      },
      entryContext: null, view: 'canvas',
    } as never)
  })

  it('gives the chat header the primary colour when it is active', () => {
    useChatStore.setState({
      canvasDirective: {
        allowedTools: [], targetFace: null, autoOpen: null,
        instructions: null, showDone: false, unlockAll: false,
      },
    } as never)
    render(<CustomiseStudio />)
    // The chat is the active half at a no-tool step, so its header is filled.
    expect(screen.getByRole('status').className).toContain('bg-accent')
  })

  it('gives the canvas header the customer bubble colour when it is active', () => {
    useChatStore.setState({
      canvasDirective: {
        allowedTools: ['upload'], targetFace: null, autoOpen: null,
        instructions: null, showDone: true, unlockAll: false,
      },
    } as never)
    render(<CustomiseStudio />)
    expect(screen.getByRole('status').className).toContain('bg-chatUserBubble')
  })
})
