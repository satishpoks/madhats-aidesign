import { describe, expect, it, beforeEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../components/DesignStudio/Surface', () => ({
  DesignStudioSurface: () => <div data-testid="surface" />,
}))
vi.mock('../components/CustomiseStudio/ChatColumn', () => ({
  ChatColumn: () => <div data-testid="chat-column" />,
}))

// jsdom ships no matchMedia, so useIsDesktop falls back to `true`. Stub it to
// drive the phone branch. Feature detection is what makes this stub-able at all.
function setViewport(desktop: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: desktop, media: query, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    }),
  })
}

import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import { CustomiseStudio } from '../components/CustomiseStudio'

const directive = (allowedTools: string[], showDone = false) => ({
  allowedTools, targetFace: null, autoOpen: null,
  instructions: null, showDone, unlockAll: false,
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

describe('phone: one panel at a time', () => {
  beforeEach(() => setViewport(false))

  it('opens on the chat', () => {
    render(<CustomiseStudio />)
    expect(screen.getByTestId('tab-chat')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('canvas-column').className).toContain('hidden')
    expect(screen.getByTestId('chat-column-wrap').className).not.toContain('hidden')
  })

  it('keeps the hidden panel MOUNTED', () => {
    // Surface.doRender() flattens through stageRef in a loop over the decorated
    // faces. Unmounting the Konva stage would null that ref and break finalize
    // outright, and remounting would lose the in-progress design. Hiding is the
    // only safe way to show one panel at a time.
    render(<CustomiseStudio />)
    expect(screen.getByTestId('surface')).toBeInTheDocument()
    expect(screen.getByTestId('chat-column')).toBeInTheDocument()
  })

  it('auto-switches to the canvas when the flow needs the canvas', () => {
    render(<CustomiseStudio />)
    act(() => {
      useChatStore.setState({ canvasDirective: directive(['upload'], true) } as never)
    })
    expect(screen.getByTestId('tab-canvas')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('canvas-column').className).not.toContain('hidden')
  })

  it('lets the customer peek at the other panel, and the peek sticks', async () => {
    const user = userEvent.setup()
    render(<CustomiseStudio />)
    await user.click(screen.getByTestId('tab-canvas'))
    expect(screen.getByTestId('tab-canvas')).toHaveAttribute('aria-selected', 'true')
    // A re-render with the SAME active surface must not snap the peek back —
    // the sync effect is keyed on `active` changing, not on every render.
    act(() => { useChatStore.setState({ sending: true } as never) })
    expect(screen.getByTestId('tab-canvas')).toHaveAttribute('aria-selected', 'true')
  })

  it('forces the canvas visible while the design is being captured', () => {
    // At finalize_canvas the directive hands over no tool, so the chat is the
    // "active surface" and the canvas would be display:none during the
    // multi-face flatten loop. Rather than rely on Konva painting a hidden
    // element, force the tab.
    render(<CustomiseStudio />)
    act(() => { useChatStore.setState({ triggerFinalize: true } as never) })
    expect(screen.getByTestId('tab-canvas')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('canvas-column').className).not.toContain('hidden')
  })
})

describe('desktop: both panels, no tabs', () => {
  beforeEach(() => setViewport(true))

  it('renders no tab bar and hides neither panel', () => {
    render(<CustomiseStudio />)
    expect(screen.queryByTestId('panel-tabs')).not.toBeInTheDocument()
    expect(screen.getByTestId('canvas-column').className).not.toContain('hidden')
    expect(screen.getByTestId('chat-column-wrap').className).not.toContain('hidden')
  })
})
