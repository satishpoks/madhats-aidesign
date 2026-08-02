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
  // `basis-[45vh]` dated from when BOTH halves stacked on one screen at once
  // (the chat was deliberately capped so the canvas got the rest of the row).
  // Panels are now shown one at a time on mobile (PanelTabs; the other column
  // gets `hidden` and contributes no height), so a 45vh cap on the shown panel
  // just left ~55% of the row empty under it — the "messages are barely
  // visible" bug report. The fix is `flex-1` (grow+shrink+basis-0) so the
  // shown panel fills the whole row; superseded assertion below (this
  // comment is the "why", the test is the "what").
  it('lets the shown panel fill the row on mobile, not a hard 45vh', () => {
    render(<CustomiseStudio />)
    const chat = screen.getByTestId('chat-column-wrap')
    expect(chat.className).not.toContain('basis-[45vh]')
    expect(chat.className).toMatch(/(^|\s)flex-1(\s|$)/)
    expect(chat.className).toContain('min-h-0')
    expect(chat.className).not.toMatch(/(^|\s)h-\[45vh\]/)
  })

  it('cancels the mobile grow/shrink/basis entirely at md — desktop keeps its fixed width', () => {
    // `flex-1` sets grow, shrink AND basis in one shorthand, so cancelling
    // only `shrink` (as the old md:shrink-0 did) would leave grow:1 active at
    // md and let the column expand past its fixed width under desktop space
    // pressure. md:flex-none cancels all three. See
    // customiseStudioFocus.test.tsx / CustomiseStudio.test.tsx for
    // confirmation the fixed-width classes themselves are untouched.
    render(<CustomiseStudio />)
    const chat = screen.getByTestId('chat-column-wrap')
    // Matched as a whole class token, not toContain — mobileLayout regressed
    // once already from a substring match (see mobilePanelTabs.test.tsx's
    // note on the same lesson).
    expect(chat.className).toMatch(/(^|\s)flex-1(\s|$)/)
    expect(chat.className).toMatch(/(^|\s)md:flex-none(\s|$)/)
  })

  it('keeps the desktop fixed-width classes intact', () => {
    render(<CustomiseStudio />)
    const chat = screen.getByTestId('chat-column-wrap')
    // Whole-class-token regexes, not toContain — a substring match on a
    // bracketed pixel value is not the live-bug-prone case `overflow-hidden`/
    // `hidden` was (these values are effectively unique), but this file is
    // the one place that documents the rule, so stay consistent with it.
    expect(chat.className).toMatch(/(^|\s)md:w-\[360px\](\s|$)/)
    expect(chat.className).toMatch(/(^|\s)lg:w-\[420px\](\s|$)/)
    expect(chat.className).toMatch(/(^|\s)xl:w-\[480px\](\s|$)/)
    expect(chat.className).toMatch(/(^|\s)2xl:w-\[560px\](\s|$)/)
  })

  it("gives the canvas column the same flex-1 fill when it's the shown panel", () => {
    // The canvas column was already `flex-1` unconditionally (desktop relied
    // on it), so it needs no change — pin that it still fills the row when
    // shown alone on mobile too.
    render(<CustomiseStudio />)
    const canvas = screen.getByTestId('canvas-column')
    expect(canvas.className).toMatch(/(^|\s)flex-1(\s|$)/)
    expect(canvas.className).toContain('min-h-0')
  })

  it('stacks the two halves on a phone and rows them from md', () => {
    render(<CustomiseStudio />)
    const row = screen.getByTestId('canvas-column').parentElement!
    expect(row.className).toContain('flex-col')
    expect(row.className).toContain('md:flex-row')
  })
})
