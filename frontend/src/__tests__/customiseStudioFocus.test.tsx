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
    // showDone:true is what makes this a canvas-work step (LOGO_ADJUST-shaped) —
    // a tool being merely allowed is not enough (see the ASK_LOGO_PLACEMENT
    // case below).
    useChatStore.setState({ canvasDirective: { ...directive(['upload']), showDone: true } } as never)
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
    useChatStore.setState({ canvasDirective: { ...directive(['upload']), showDone: true } } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('canvas-column').className).toContain('ring-2')
    expect(screen.getByTestId('chat-column-wrap').className).toContain('opacity-60')
  })

  it('never blocks pointer events on the inactive column', () => {
    // Dimming is a CUE, not a lock. The real locking is per-affordance
    // (stageLocked, ToolRail allowedTools, ChatColumn inputLocked). Blocking
    // pointer events here would also stop the customer scrolling back through
    // the thread or re-reading the cap, which they must always be able to do.
    useChatStore.setState({ canvasDirective: { ...directive(['upload']), showDone: true } } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('chat-column-wrap').className)
      .not.toContain('pointer-events-none')
  })

  it('names the surface in the pill so the cue is not colour-only', () => {
    useChatStore.setState({ canvasDirective: { ...directive(['upload']), showDone: true } } as never)
    render(<CustomiseStudio />)
    expect(screen.getByRole('status').textContent).toMatch(/design here/i)
  })

  it('moves the pill to the chat on a chat step', () => {
    useChatStore.setState({ canvasDirective: directive([]) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByRole('status').textContent).toMatch(/answer here/i)
  })

  it('puts the ring and pill on the CHAT column at ASK_LOGO_PLACEMENT — tool allowed, no showDone/autoOpen', () => {
    // Regression for the reported bug: the step hands over the upload tool
    // (so the just-placed logo stays selectable) but asks the face via chat
    // chips. A tool being allowed must not, by itself, ring the canvas.
    useChatStore.setState({ canvasDirective: directive(['upload']) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('chat-column-wrap').dataset.active).toBe('true')
    expect(screen.getByTestId('chat-column-wrap').className).toContain('ring-2')
    expect(screen.getByTestId('canvas-column').dataset.active).toBe('false')
    expect(screen.getByRole('status').textContent).toMatch(/answer here/i)
  })

  it('suppresses the chat pill at await_email_verify but keeps the ring', () => {
    // ChatColumn's inputLocked disables the box/Send/mic/chips/Back here, so a
    // "Your turn — answer here" pill would point at a dead input. The chat IS
    // still where the customer should be looking (the waiting panel is there),
    // so the ring/dim cue must stay — only the pill goes.
    useChatStore.setState({ canvasDirective: null, chatState: 'await_email_verify' } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('chat-column-wrap').dataset.active).toBe('true')
    expect(screen.getByTestId('chat-column-wrap').className).toContain('ring-2')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByText(/your turn/i)).not.toBeInTheDocument()
  })

  it('suppresses the chat pill during generating (v1-delegated, null directive)', () => {
    useChatStore.setState({ canvasDirective: null, chatState: 'generating' } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('chat-column-wrap').dataset.active).toBe('true')
    expect(screen.queryByText(/your turn/i)).not.toBeInTheDocument()
  })

  it('suppresses the chat pill during regenerating (v1-delegated, null directive)', () => {
    useChatStore.setState({ canvasDirective: null, chatState: 'regenerating' } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('chat-column-wrap').dataset.active).toBe('true')
    expect(screen.queryByText(/your turn/i)).not.toBeInTheDocument()
  })
})
