import { beforeEach, describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useActiveSurface } from '../lib/useActiveSurface'
import { useChatStore } from '../store/chatStore'

const directive = (allowedTools: string[]) => ({
  allowedTools, targetFace: null, autoOpen: null,
  instructions: null, showDone: false, unlockAll: false,
})

beforeEach(() => useChatStore.getState().reset())

describe('useActiveSurface', () => {
  it('is the chat when a tool is merely allowed with no Done and no auto-open — ASK_LOGO_PLACEMENT', () => {
    // ASK_LOGO_PLACEMENT declares tool:"upload" (to keep the just-added logo
    // selectable) but asks the face via chat chips (Front/Back/Left/Right).
    // A tool being allowed is not the same as there being canvas work to do.
    useChatStore.setState({ canvasDirective: directive(['upload']) } as never)
    expect(renderHook(() => useActiveSurface()).result.current).toBe('chat')
  })

  it('is the canvas when the directive sets showDone — a place/drag/adjust-then-Done step', () => {
    useChatStore.setState({
      canvasDirective: { ...directive(['upload']), showDone: true },
    } as never)
    expect(renderHook(() => useActiveSurface()).result.current).toBe('canvas')
  })

  it('is the canvas when the directive sets autoOpen — the step opens a tool dialog for the customer', () => {
    useChatStore.setState({
      canvasDirective: { ...directive(['upload']), autoOpen: 'upload' },
    } as never)
    expect(renderHook(() => useActiveSurface()).result.current).toBe('canvas')
  })

  it('is the chat when the v2 directive hands over no tool', () => {
    useChatStore.setState({ canvasDirective: directive([]) } as never)
    expect(renderHook(() => useActiveSurface()).result.current).toBe('chat')
  })

  it('is the canvas while a rejected finalize has re-opened it', () => {
    // FINALIZE_CANVAS's directive is `allowed_tools: []`, but the canvas IS
    // live — the customer has to edit the text the gate rejected.
    useChatStore.setState({
      canvasDirective: directive([]), finalizeFailed: true,
    } as never)
    expect(renderHook(() => useActiveSurface()).result.current).toBe('canvas')
  })

  it('falls back to the v1 whole-rail gate when there is no directive', () => {
    useChatStore.setState({ canvasDirective: null, chatState: 'canvas_design' } as never)
    expect(renderHook(() => useActiveSurface()).result.current).toBe('canvas')
    useChatStore.setState({ canvasDirective: null, chatState: 'ask_quantity' } as never)
    expect(renderHook(() => useActiveSurface()).result.current).toBe('chat')
  })
})
