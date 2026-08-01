import { create } from 'zustand'
import { sendChat, sendBack, pollVerification, pollRegeneration, pollGenerationAdvance, ApiError } from '../lib/api'
import type { ChatMessageOut } from '../lib/types'
import { parseCanvasOps, applyCanvasOps } from '../lib/canvasOps'
import { useCanvasStore, type CanvasDesign } from './canvasStore'

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
  progress: { step: number; total: number; sections?: string[]; section?: number } | null
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
  /** v2 canvas checkpoint restore: the checkpoints available to rewind to on
   *  THIS turn, newest first. Empty/absent means render no Back control at
   *  all — the backend already filters out superseded/frozen checkpoints. */
  backTargets: { seq: number; label: string; kind: string }[]
  /** The customer's captured name, once the backend has it (else null). Powers
   *  the "Design for <Name>" banner above the canvas — display-only, never
   *  logged (security rule 10: no PII in logs/breadcrumbs). */
  collectedName: string | null
  /** v2 canvas: a finalize was REJECTED (e.g. the cap-text profanity gate), so
   *  the canvas is re-opened for the customer to act on the error even though
   *  FINALIZE_CANVAS's directive hands over no tool. Lives here rather than in
   *  Surface's local state because useActiveSurface must see it — otherwise the
   *  focus cue says "chat" while the canvas is genuinely live. */
  finalizeFailed: boolean
  /** Whether the on-screen design (and the emailed preview) should be shown
   *  watermarked. Absent on a shared-tail turn (no registry step, so the
   *  backend sends no flag) defaults to watermarked — the design is finished
   *  in every one of those states. Only an explicit `false` clears it. */
  watermark: boolean

  kickoff: (sessionId: string) => Promise<void>
  sendMessage: (sessionId: string, text: string) => Promise<void>
  /** v2 canvas checkpoint restore: rewind the session to `seq` and apply the
   *  restored turn (including the canvas snapshot, if the checkpoint has one). */
  goBackTo: (sessionId: string, seq: number) => Promise<void>
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

/** Shown when POST /chat/{id}/back 409s: the checkpoint the customer tapped is
 *  gone (superseded by another tab, already used, or frozen since the menu was
 *  rendered). Names the next move explicitly — the conversation has NOT moved,
 *  so the question above is still the live one. */
export const BACK_UNAVAILABLE =
  "That step can't be changed any more — please carry on from the question above."

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
    ? (data.progress as { step: number; total: number; sections?: string[]; section?: number })
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
  const backTargets = Array.isArray(data.back_targets)
    ? (data.back_targets as { seq: number; label: string; kind: string }[])
    : []
  const collectedName = typeof data.designer_name === 'string' ? data.designer_name : null
  // Further assistant messages to append AFTER `reply`, each as its own bubble
  // (backend orchestrator_v2._persist). Absent on every ordinary turn.
  const extraReplies = Array.isArray(data.extra_replies)
    ? (data.extra_replies as string[]).filter(t => typeof t === 'string')
    : []
  // Absent on a shared-tail turn (no registry step, so the backend sends no
  // flag) — and the design is finished in every one of those states, so the
  // safe default is watermarked. Only an explicit `false` clears it.
  const watermark = data.watermark !== false
  return { options, options2, triggerGeneration, triggerRegeneration, continuable, tintReady, tintHex, colourSwatches, colourPicker, progress, multiselect, selected, quoteUrl, canvasDirective, triggerFinalize, backTargets, collectedName, extraReplies, watermark }
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10)
}

/** The assistant bubbles one response produces: the main reply, then each
 *  extra, in order. Shared by every response handler so a split turn can never
 *  render in one place and not another. */
function assistantMessages(reply: string, extraReplies: string[]): ChatMessage[] {
  return [reply, ...extraReplies].map(text => ({ id: uid(), role: 'assistant' as const, text }))
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
  backTargets: [],
  collectedName: null,
  finalizeFailed: false,
  // Nothing is designed yet at mount — differs from parseData's default
  // (watermarked) on purpose.
  watermark: false,

  kickoff: async (sessionId: string) => {
    if (get().kickoffDone) return
    set({ kickoffDone: true, sending: true, chatError: null })
    try {
      const res = await sendChat(sessionId, '')
      const { extraReplies, ...parsed } = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          ...assistantMessages(res.reply, extraReplies),
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
    // Never send a blank/whitespace user turn. This is the single choke point
    // every user message flows through (chips, typed input, "done"/"ok"/"none",
    // uploads). Only kickoff() legitimately sends "" — and it's a separate
    // function. An empty turn reaching the backend is read as a real answer by
    // the v2 interpreter and walked the conversation backward to ask_name
    // (the live canvas dead-loop). Drop it here so no UI path can emit one.
    if (!text.trim()) return
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
      // Sent on the two v1-owned tail states that read the live canvas for
      // their own logic (describe_changes: resolve an edit against what's on
      // screen; logo_adjust: the Done turn closing logo placement, so a
      // self-ticked "Remove background" is seen — canvas_steps.observe_canvas)
      // PLUS every v2-owned turn: the backend snapshots the canvas into the
      // Back checkpoint on every v2 turn. A null canvasDirective means "not a
      // v2 turn" (see useActiveSurface.ts) — a plain Q&A (non-canvas) session
      // never receives one, so it keeps sending nothing, exactly as before.
      // rework_canvas is v2-owned (covered by the directive check already;
      // named explicitly too since chat.py's persist path names it alongside
      // describe_changes). Which turns may PERSIST the blob to
      // design_sessions.canvas_design is unchanged and still enforced
      // server-side (chat.py::_persist_live_canvas_design).
      const st = get().chatState
      const isV2Turn = get().canvasDirective !== null
      const liveDesign = (isV2Turn || st === 'describe_changes' || st === 'logo_adjust' || st === 'rework_canvas')
        ? useCanvasStore.getState().toCanvasDesign()
        : undefined
      const res = await sendChat(sessionId, text, liveDesign)
      const { extraReplies, ...parsed } = parseData(res.data)
      applyCanvasOps(parseCanvasOps(res.data))   // before set(): patch, then Surface's lock effect
      set(state => ({
        messages: [
          ...state.messages,
          ...assistantMessages(res.reply, extraReplies),
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

  goBackTo: async (sessionId: string, seq: number) => {
    if (get().sending) return
    set({ sending: true })
    try {
      const res = await sendBack(sessionId, seq)
      const data = res.data as Record<string, unknown>
      // Applied HERE, in the response handler — never in a React effect. An
      // effect fires on change and would re-apply on resume, restoring a
      // canvas the customer has since moved on from.
      const snap = data.canvas_restore
      if (snap && typeof snap === 'object') {
        useCanvasStore.getState().restoreSnapshot(snap as CanvasDesign)
      }
      // The backend supersedes everything after the restore point but the
      // in-memory thread only ever grows via append — so without this the
      // discarded exchange stays visible above the fresh question, reading as
      // a contradiction (questions the customer just rewound past, followed
      // by the conversation restarting). `data.messages` is the live thread,
      // already ending with the new reply (orchestrator_v2.handle_back reads
      // it AFTER persisting), so it REPLACES the store's messages instead of
      // going through `applyResponse`'s append — applying the reply twice
      // otherwise. Absent (a non-v2 turn or an older backend) falls back to
      // the old append behaviour.
      const restoredMessages = data.messages
      if (Array.isArray(restoredMessages)) {
        // Discarded, not appended, same as `hydrate`: `messages` already
        // contains every extra row (`_persist` wrote each one), so replaying
        // `extraReplies` on top would duplicate the reply.
        const { extraReplies: _ignored, ...parsed } = parseData(data)
        set({
          messages: (restoredMessages as ChatMessageOut[]).map(m => ({
            id: uid(),
            role: m.role,
            text: m.content,
          })),
          chatState: res.state,
          ...parsed,
          chatError: null,
        })
      } else {
        get().applyResponse(res.reply, res.state, data)
      }
    } catch (err) {
      // Without this the whole failure path was silent: the menu closed, the
      // conversation did not move, nothing was shown, and the rejection escaped
      // to window.onunhandledrejection. 409 is the expected, benign case — a
      // stale tab, a double tap, or a checkpoint that has frozen since the menu
      // was rendered (offerability is re-checked server-side).
      const stale = err instanceof ApiError && err.status === 409
      set(state => ({
        chatError: stale
          ? BACK_UNAVAILABLE
          : err instanceof Error ? err.message : 'Something went wrong',
        // Drop the destination that just proved unavailable so the menu cannot
        // offer it again; when it was the only one the Back button disappears,
        // which is already how "no going back" is expressed.
        backTargets: stale
          ? state.backTargets.filter(t => t.seq !== seq)
          : state.backTargets,
      }))
    } finally {
      set({ sending: false })
    }
  },

  hydrate: (messages, state, data) => {
    // Discarded, not appended: `messages` already contains the extra rows —
    // _persist persisted each one — so re-appending would duplicate them.
    const { extraReplies: _ignored, ...parsed } = parseData(data)
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
    const { extraReplies, ...parsed } = parseData(data)
    set(s => ({
      messages: [...s.messages, ...assistantMessages(reply, extraReplies)],
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
      const { extraReplies, ...parsed } = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          ...assistantMessages(res.reply as string, extraReplies),
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
      const { extraReplies, ...parsed } = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          ...assistantMessages(res.reply as string, extraReplies),
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
      const { extraReplies, ...parsed } = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          ...assistantMessages(res.reply as string, extraReplies),
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
      backTargets: [],
      collectedName: null,
      finalizeFailed: false,
      watermark: false,
    }),
}))
