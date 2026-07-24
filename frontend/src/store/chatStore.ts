import { create } from 'zustand'
import { sendChat, sendBack, pollVerification, pollRegeneration, pollGenerationAdvance } from '../lib/api'
import type { ChatMessageOut } from '../lib/types'
import { parseCanvasOps, applyCanvasOps } from '../lib/canvasOps'
import { useCanvasStore } from './canvasStore'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
}

interface ChatStoreState {
  messages: ChatMessage[]
  chatState: string
  options: string[]
  options2: string[]
  triggerGeneration: boolean
  triggerRegeneration: boolean
  /** Statement-only state: show a "Continue" affordance, not a text answer. */
  continuable: boolean
  /** Blank flow: a colour has been chosen — the left viewer can show the tinted
   *  (composited) blank. `tintHex` is the chosen colour so a change re-tints. */
  tintReady: boolean
  tintHex: string
  /** Colourway swatches offered at the hat-colour step (name + hex). */
  colourSwatches: { name: string; hex: string }[]
  /** Blank flow: the hat-colour step wants a free colour picker (custom hex). */
  colourPicker: boolean
  progress: { step: number; total: number } | null
  /** ask_decoration: the option chips are a multi-select set. */
  multiselect: boolean
  /** ask_decoration: currently-selected decoration names. */
  selected: string[]
  /** session_end: the /quote link to open (customer asked to request a quote). */
  quoteUrl: string
  sending: boolean
  chatError: string | null
  /** Guard so kickoff() sends the empty-string turn only once per session. */
  kickoffDone: boolean
  /** v2 canvas flow: the current tool-control directive (null = no change). */
  canvasDirective: {
    allowedTools: string[]
    targetFace: string | null
    autoOpen: string | null
    instructions: string | null
    showDone: boolean
    /** REWORK_CANVAS: the customer reopened a finished design — clear every
     *  element's locked flag so the whole canvas is editable again. */
    unlockAll: boolean
  } | null
  /** v2: the frontend should flatten + finalize the canvas now. */
  triggerFinalize: boolean
  /** v2 canvas correction: whether there's a previous answer to undo (drives
   *  the "↩ Back" control). */
  canGoBack: boolean

  kickoff: (sessionId: string) => Promise<void>
  sendMessage: (sessionId: string, text: string) => Promise<void>
  /** v2 canvas correction: undo the last answered step and apply the re-ask. */
  goBack: (sessionId: string) => Promise<void>
  /** Rebuild the thread from persisted history when resuming a session. */
  hydrate: (
    messages: ChatMessageOut[],
    state: string,
    data: Record<string, unknown>,
  ) => void
  /** Append an assistant reply + apply state/data without wiping history
   *  (used by the canvas "Done designing" handoff into the outro). */
  applyResponse: (reply: string, state: string, data: Record<string, unknown>) => void
  /** Poll for out-of-band email verification; advances the thread once verified. */
  pollVerification: (sessionId: string) => Promise<void>
  /** One-shot advance from regenerating -> offer_refine, called after regeneration settles. */
  advanceRegeneration: (sessionId: string) => Promise<void>
  /** One-shot advance from generating -> verify/offer_refine, after generation settles. */
  advanceGeneration: (sessionId: string) => Promise<void>
  dismissError: () => void
  setError: (msg: string) => void
  reset: () => void
}

function parseData(data: Record<string, unknown>) {
  const options = Array.isArray(data.options) ? (data.options as string[]) : []
  const options2 = Array.isArray(data.options2) ? (data.options2 as string[]) : []
  const triggerGeneration = data.trigger_generation === true
  const triggerRegeneration = data.trigger_regeneration === true
  const continuable = data.continuable === true
  const tintReady = data.tint_ready === true
  const tintHex = typeof data.tint_hex === 'string' ? data.tint_hex : ''
  const colourSwatches = Array.isArray(data.colour_swatches)
    ? (data.colour_swatches as { name: string; hex: string }[])
    : []
  const colourPicker = data.colour_picker === true
  const progress = (data.progress && typeof data.progress === 'object')
    ? (data.progress as { step: number; total: number })
    : null
  const multiselect = data.multiselect === true
  const selected = Array.isArray(data.selected) ? (data.selected as string[]) : []
  const quoteUrl = typeof data.quote_url === 'string' ? data.quote_url : ''
  const rawCanvas = (data.canvas && typeof data.canvas === 'object') ? data.canvas as Record<string, unknown> : null
  const canvasDirective = rawCanvas
    ? {
        allowedTools: Array.isArray(rawCanvas.allowed_tools) ? rawCanvas.allowed_tools as string[] : [],
        targetFace: typeof rawCanvas.target_face === 'string' ? rawCanvas.target_face : null,
        autoOpen: typeof rawCanvas.auto_open === 'string' ? rawCanvas.auto_open : null,
        instructions: typeof rawCanvas.instructions === 'string' ? rawCanvas.instructions : null,
        showDone: rawCanvas.show_done === true,
        unlockAll: rawCanvas.unlock_all === true,
      }
    : null
  const triggerFinalize = data.trigger_finalize === true
  const canGoBack = data.can_go_back === true
  return { options, options2, triggerGeneration, triggerRegeneration, continuable, tintReady, tintHex, colourSwatches, colourPicker, progress, multiselect, selected, quoteUrl, canvasDirective, triggerFinalize, canGoBack }
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10)
}

export const useChatStore = create<ChatStoreState>((set, get) => ({
  messages: [],
  chatState: '',
  options: [],
  options2: [],
  triggerGeneration: false,
  triggerRegeneration: false,
  continuable: false,
  tintReady: false,
  tintHex: '',
  colourSwatches: [],
  colourPicker: false,
  progress: null,
  multiselect: false,
  selected: [],
  quoteUrl: '',
  sending: false,
  chatError: null,
  kickoffDone: false,
  canvasDirective: null,
  triggerFinalize: false,
  canGoBack: false,

  kickoff: async (sessionId: string) => {
    if (get().kickoffDone) return
    set({ kickoffDone: true, sending: true, chatError: null })
    try {
      const res = await sendChat(sessionId, '')
      const parsed = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          { id: uid(), role: 'assistant', text: res.reply },
        ],
        chatState: res.state,
        ...parsed,
        sending: false,
      }))
    } catch (err) {
      set({
        chatError: err instanceof Error ? err.message : 'Something went wrong',
        sending: false,
        // Allow kickoff to be retried if it failed
        kickoffDone: false,
      })
    }
  },

  sendMessage: async (sessionId: string, text: string) => {
    if (get().sending) return
    set(state => ({
      messages: [
        ...state.messages,
        { id: uid(), role: 'user', text },
      ],
      sending: true,
      chatError: null,
      // Clear chips while waiting for the reply
      options: [],
      options2: [],
    }))
    try {
      // On a describe-a-change turn, send the live canvas so the backend edits
      // against what's on screen (accumulated edits), not the last saved design.
      const liveDesign = get().chatState === 'describe_changes'
        ? useCanvasStore.getState().toCanvasDesign()
        : undefined
      const res = await sendChat(sessionId, text, liveDesign)
      const parsed = parseData(res.data)
      applyCanvasOps(parseCanvasOps(res.data))   // before set(): patch, then Surface's lock effect
      set(state => ({
        messages: [
          ...state.messages,
          { id: uid(), role: 'assistant', text: res.reply },
        ],
        chatState: res.state,
        ...parsed,
        sending: false,
      }))
    } catch (err) {
      set({
        chatError: err instanceof Error ? err.message : 'Something went wrong',
        sending: false,
      })
    }
  },

  goBack: async (sessionId: string) => {
    if (get().sending) return
    set({ sending: true })
    try {
      const res = await sendBack(sessionId)
      get().applyResponse(res.reply, res.state, res.data as Record<string, unknown>)
    } finally {
      set({ sending: false })
    }
  },

  hydrate: (messages, state, data) => {
    const parsed = parseData(data)
    set({
      messages: messages.map(m => ({
        id: uid(),
        role: m.role,
        text: m.content,
      })),
      chatState: state,
      ...parsed,
      sending: false,
      chatError: null,
      // The thread already exists — never fire the greeting kickoff on resume.
      kickoffDone: true,
    })
  },

  applyResponse: (reply, state, data) => {
    const parsed = parseData(data)
    set(s => ({
      messages: [...s.messages, { id: uid(), role: 'assistant', text: reply }],
      chatState: state,
      ...parsed,
      sending: false,
      chatError: null,
    }))
  },

  pollVerification: async (sessionId: string) => {
    // Skip while a normal send is mid-flight to avoid interleaving replies.
    if (get().sending) return
    try {
      const res = await pollVerification(sessionId)
      if (res.reply == null) return // not verified yet — nothing to show
      const parsed = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          { id: uid(), role: 'assistant', text: res.reply as string },
        ],
        chatState: res.state,
        ...parsed,
      }))
    } catch {
      // Polling is best-effort — a transient failure just retries next tick.
    }
  },

  advanceRegeneration: async (sessionId: string) => {
    try {
      const res = await pollRegeneration(sessionId)
      if (res.reply == null) return // not at regenerating (already advanced, or n/a)
      const parsed = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          { id: uid(), role: 'assistant', text: res.reply as string },
        ],
        chatState: res.state,
        ...parsed,
      }))
    } catch {
      // Best-effort — a transient failure leaves the thread as-is rather than
      // throwing; the customer can still act on the design in the viewer.
    }
  },

  advanceGeneration: async (sessionId: string) => {
    try {
      const res = await pollGenerationAdvance(sessionId)
      if (res.reply == null) return // not at generating (already advanced, or n/a)
      const parsed = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          { id: uid(), role: 'assistant', text: res.reply as string },
        ],
        chatState: res.state,
        ...parsed,
      }))
    } catch {
      // Best-effort — a transient failure leaves the thread as-is; the verify
      // poll / backfill still delivers the design.
    }
  },

  dismissError: () => set({ chatError: null }),

  setError: (msg: string) => set({ chatError: msg }),

  reset: () =>
    set({
      messages: [],
      chatState: '',
      options: [],
      options2: [],
      triggerGeneration: false,
      triggerRegeneration: false,
      continuable: false,
      tintReady: false,
      tintHex: '',
      colourSwatches: [],
      colourPicker: false,
      progress: null,
      multiselect: false,
      selected: [],
      quoteUrl: '',
      sending: false,
      chatError: null,
      kickoffDone: false,
      canvasDirective: null,
      triggerFinalize: false,
      canGoBack: false,
    }),
}))
