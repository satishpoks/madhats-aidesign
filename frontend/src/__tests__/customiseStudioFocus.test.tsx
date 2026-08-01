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

  it('fills the active column header and leaves the resting one quiet', () => {
    useChatStore.setState({ canvasDirective: directive([]) } as never)
    render(<CustomiseStudio />)
    const chat = screen.getByTestId('chat-column-wrap')
    const canvas = screen.getByTestId('canvas-column')
    expect(chat).toHaveAttribute('data-active', 'true')
    expect(canvas).toHaveAttribute('data-active', 'false')
    // The active header states the turn; the resting one just names its half.
    expect(screen.getByText('Your turn — answer here')).toBeInTheDocument()
    expect(screen.getByText('Your design')).toBeInTheDocument()
  })

  it('announces the active surface without relying on colour', () => {
    useChatStore.setState({ canvasDirective: directive([]) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByRole('status')).toHaveTextContent('Your turn — answer here')
  })

  it('never blocks pointer events on the resting column', () => {
    // Dimming is a cue, not a lock — real locking is per-affordance. Blocking
    // events here would stop the customer scrolling back through the thread or
    // re-reading the cap, which they must always be able to do.
    useChatStore.setState({ canvasDirective: directive([]) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('canvas-column').className).not.toContain('pointer-events-none')
  })

  it('does not dim the resting column wholesale', () => {
    // opacity-60 on the container faded live text to grey, so the resting half
    // read as disabled or mid-error. Only its CONTENT softens now.
    useChatStore.setState({ canvasDirective: directive([]) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('canvas-column').className).not.toContain('opacity-60')
  })

  it('puts the active header on the CHAT column at ASK_LOGO_PLACEMENT — tool allowed, no showDone/autoOpen', () => {
    // Regression for the reported bug: the step hands over the upload tool
    // (so the just-placed logo stays selectable) but asks the face via chat
    // chips. A tool being allowed must not, by itself, activate the canvas.
    useChatStore.setState({ canvasDirective: directive(['upload']) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('chat-column-wrap').dataset.active).toBe('true')
    expect(screen.getByTestId('canvas-column').dataset.active).toBe('false')
    expect(screen.getByRole('status').textContent).toMatch(/answer here/i)
  })

  it('suppresses the chat status header at await_email_verify but keeps the chat active', () => {
    // ChatColumn's inputLocked disables the box/Send/mic/chips/Back here, so a
    // "Your turn — answer here" header would point at a dead input. The chat IS
    // still where the customer should be looking (the waiting panel is there),
    // so the active card cue must stay — only the status text goes.
    useChatStore.setState({ canvasDirective: null, chatState: 'await_email_verify' } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('chat-column-wrap').dataset.active).toBe('true')
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
