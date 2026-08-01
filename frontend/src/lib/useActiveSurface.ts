import { useChatStore } from '../store/chatStore'

export type ActiveSurface = 'canvas' | 'chat'

/**
 * Which panel the customer should act in on THIS turn.
 *
 * The backend already answers this: every v2-owned step emits a canvas
 * directive, and a step that hands over a tool is a canvas step while every
 * other step returns `allowed_tools: []`. Deriving it once here (rather than
 * in each panel) is what stops the two columns disagreeing about who is active
 * — a contradiction is worse than no cue at all.
 *
 * `finalizeFailed` is an explicit exception: FINALIZE_CANVAS hands over no
 * tool, but a REJECTED finalize re-opens the canvas so the customer can fix
 * what the gate refused (see Surface.doRender's catch). Reading the directive
 * alone would point them at the chat while the thing they must edit is on the
 * canvas.
 *
 * No directive at all means this is not a v2 turn — a v1 session, or a shared
 * tail state — so fall back to v1's existing whole-rail gate.
 */
export function useActiveSurface(): ActiveSurface {
  const canvasDirective = useChatStore(s => s.canvasDirective)
  const chatState = useChatStore(s => s.chatState)
  const finalizeFailed = useChatStore(s => s.finalizeFailed)

  if (canvasDirective === null) {
    return chatState === 'canvas_design' ? 'canvas' : 'chat'
  }
  return canvasDirective.allowedTools.length > 0 || finalizeFailed ? 'canvas' : 'chat'
}
