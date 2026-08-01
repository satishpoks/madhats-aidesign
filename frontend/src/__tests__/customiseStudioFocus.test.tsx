import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../components/DesignStudio/Surface', () => ({
  DesignStudioSurface: () => <div data-testid="surface" />,
}))
vi.mock('../components/CustomiseStudio/ChatColumn', () => ({
  ChatColumn: () => <div data-testid="chat-column" />,
}))

import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import { CustomiseStudio } from '../components/CustomiseStudio'

const directive = (allowedTools: string[]) => ({
  allowedTools, targetFace: null, autoOpen: null,
  instructions: null, showDone: false, unlockAll: false,
})

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

describe('CustomiseStudio focus cue', () => {
  it('marks the canvas active and the chat inactive on a canvas step', () => {
    useChatStore.setState({ canvasDirective: directive(['upload']) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('canvas-column').dataset.active).toBe('true')
    expect(screen.getByTestId('chat-column-wrap').dataset.active).toBe('false')
  })

  it('marks the chat active and the canvas inactive on a chat step', () => {
    useChatStore.setState({ canvasDirective: directive([]) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('chat-column-wrap').dataset.active).toBe('true')
    expect(screen.getByTestId('canvas-column').dataset.active).toBe('false')
  })

  it('rings the active column and dims the inactive one', () => {
    useChatStore.setState({ canvasDirective: directive(['upload']) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('canvas-column').className).toContain('ring-2')
    expect(screen.getByTestId('chat-column-wrap').className).toContain('opacity-60')
  })

  it('never blocks pointer events on the inactive column', () => {
    // Dimming is a CUE, not a lock. The real locking is per-affordance
    // (stageLocked, ToolRail allowedTools, ChatColumn inputLocked). Blocking
    // pointer events here would also stop the customer scrolling back through
    // the thread or re-reading the cap, which they must always be able to do.
    useChatStore.setState({ canvasDirective: directive(['upload']) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('chat-column-wrap').className)
      .not.toContain('pointer-events-none')
  })

  it('names the surface in the pill so the cue is not colour-only', () => {
    useChatStore.setState({ canvasDirective: directive(['upload']) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByRole('status').textContent).toMatch(/design here/i)
  })

  it('moves the pill to the chat on a chat step', () => {
    useChatStore.setState({ canvasDirective: directive([]) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByRole('status').textContent).toMatch(/answer here/i)
  })
})
