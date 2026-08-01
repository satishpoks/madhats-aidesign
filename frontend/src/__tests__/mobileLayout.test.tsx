import { describe, expect, it, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Same pattern as CustomiseStudio.test.tsx / customiseStudioFocus.test.tsx:
// the real Surface mounts react-konva, which jsdom cannot host without a
// canvas 2D context stub. This file only pins wrapper class names, so the
// heavy children are mocked out rather than duplicating that stub.
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
  } as never)
})

// jsdom performs NO layout, so these pin class names, not pixels. That is the
// honest limit of what can be checked here — see the plan's verification note.
describe('phone layout', () => {
  it('gives the chat a flexible share, not a hard 45vh', () => {
    render(<CustomiseStudio />)
    const chat = screen.getByTestId('chat-column-wrap')
    expect(chat.className).toContain('basis-[45vh]')
    expect(chat.className).toContain('min-h-0')
    expect(chat.className).not.toMatch(/(^|\s)h-\[45vh\]/)
  })

  it('confines the shrink allowance to mobile — desktop keeps its fixed width', () => {
    // `shrink` is a flex property, not a width class: it applies at every
    // breakpoint unless overridden. Without md:shrink-0 the fixed
    // md:w-[360px]/lg:.../xl:.../2xl:... widths could compress under desktop
    // space pressure — a behavioural change outside this task's mobile-only
    // scope. See customiseStudioFocus.test.tsx / CustomiseStudio.test.tsx for
    // confirmation those fixed-width classes themselves are untouched.
    render(<CustomiseStudio />)
    const chat = screen.getByTestId('chat-column-wrap')
    expect(chat.className).toContain('shrink')
    expect(chat.className).toContain('md:shrink-0')
  })

  it('stacks the two halves on a phone and rows them from md', () => {
    render(<CustomiseStudio />)
    const row = screen.getByTestId('canvas-column').parentElement!
    expect(row.className).toContain('flex-col')
    expect(row.className).toContain('md:flex-row')
  })
})
