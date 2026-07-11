import { create } from 'zustand'
import { sendChat, pollVerification, pollRegeneration } from '../lib/api'
import type { ChatMessageOut } from '../lib/types'

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
  progress: { step: number; total: number } | null
  sending: boolean
  chatError: string | null
  /** Guard so kickoff() sends the empty-string turn only once per session. */
  kickoffDone: boolean

  kickoff: (sessionId: string) => Promise<void>
  sendMessage: (sessionId: string, text: string) => Promise<void>
  /** Rebuild the thread from persisted history when resuming a session. */
  hydrate: (
    messages: ChatMessageOut[],
    state: string,
    data: Record<string, unknown>,
  ) => void
  /** Poll for out-of-band email verification; advances the thread once verified. */
  pollVerification: (sessionId: string) => Promise<void>
  /** One-shot advance from regenerating -> offer_refine, called after regeneration settles. */
  advanceRegeneration: (sessionId: string) => Promise<void>
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
  const progress = (data.progress && typeof data.progress === 'object')
    ? (data.progress as { step: number; total: number })
    : null
  return { options, options2, triggerGeneration, triggerRegeneration, continuable, progress }
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
  progress: null,
  sending: false,
  chatError: null,
  kickoffDone: false,

  kickoff: async (sessionId: string) => {
    if (get().kickoffDone) return
    set({ kickoffDone: true, sending: true, chatError: null })
    try {
      const res = await sendChat(sessionId, '')
      const { options, options2, triggerGeneration, triggerRegeneration, continuable, progress } = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          { id: uid(), role: 'assistant', text: res.reply },
        ],
        chatState: res.state,
        options,
        options2,
        triggerGeneration,
        triggerRegeneration,
        continuable,
        progress,
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
      const res = await sendChat(sessionId, text)
      const { options, options2, triggerGeneration, triggerRegeneration, continuable, progress } = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          { id: uid(), role: 'assistant', text: res.reply },
        ],
        chatState: res.state,
        options,
        options2,
        triggerGeneration,
        triggerRegeneration,
        continuable,
        progress,
        sending: false,
      }))
    } catch (err) {
      set({
        chatError: err instanceof Error ? err.message : 'Something went wrong',
        sending: false,
      })
    }
  },

  hydrate: (messages, state, data) => {
    const { options, options2, triggerGeneration, triggerRegeneration, continuable, progress } = parseData(data)
    set({
      messages: messages.map(m => ({
        id: uid(),
        role: m.role,
        text: m.content,
      })),
      chatState: state,
      options,
      options2,
      triggerGeneration,
      triggerRegeneration,
      continuable,
      progress,
      sending: false,
      chatError: null,
      // The thread already exists — never fire the greeting kickoff on resume.
      kickoffDone: true,
    })
  },

  pollVerification: async (sessionId: string) => {
    // Skip while a normal send is mid-flight to avoid interleaving replies.
    if (get().sending) return
    try {
      const res = await pollVerification(sessionId)
      if (res.reply == null) return // not verified yet — nothing to show
      const { options, options2, triggerGeneration, triggerRegeneration, continuable, progress } = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          { id: uid(), role: 'assistant', text: res.reply as string },
        ],
        chatState: res.state,
        options,
        options2,
        triggerGeneration,
        triggerRegeneration,
        continuable,
        progress,
      }))
    } catch {
      // Polling is best-effort — a transient failure just retries next tick.
    }
  },

  advanceRegeneration: async (sessionId: string) => {
    try {
      const res = await pollRegeneration(sessionId)
      if (res.reply == null) return // not at regenerating (already advanced, or n/a)
      const { options, options2, triggerGeneration, triggerRegeneration, continuable, progress } = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          { id: uid(), role: 'assistant', text: res.reply as string },
        ],
        chatState: res.state,
        options,
        options2,
        triggerGeneration,
        triggerRegeneration,
        continuable,
        progress,
      }))
    } catch {
      // Best-effort — a transient failure leaves the thread as-is rather than
      // throwing; the customer can still act on the design in the viewer.
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
      progress: null,
      sending: false,
      chatError: null,
      kickoffDone: false,
    }),
}))
