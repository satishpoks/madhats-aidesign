import { useChatStore } from '../store/chatStore'

export type ActiveSurface = 'canvas' | 'chat'

/**
 * Which panel the customer should act in on THIS turn.
 *
 * The backend already answers this — but NOT via `allowedTools`. A tool being
 * allowed only means the canvas won't reject an action if the customer takes
 * one; several v2 steps hand a tool over merely to keep an element selectable
 * or a control reachable while the actual answer is a chat chip. The clearest
 * case is `ASK_LOGO_PLACEMENT`: it declares `tool: "upload"` (so the just-added
 * logo stays selectable) and asks "Which part of the cap should it go on?" with
 * Front/Back/Left/Right chips — the customer never touches the canvas there,
 * they answer in chat. Gating on `allowedTools.length > 0` rings the canvas on
 * that turn and is exactly the bug this hook exists to not have.
 *
 * The real signal is whether the step has a canvas ACTION for the customer to
 * perform: `showDone` (place/drag/adjust, then press Done — LOGO_ADJUST,
 * DECOR_ADJUST, REWORK_CANVAS) or `autoOpen` (the step opens a tool dialog for
 * them, e.g. the upload picker). A step with neither — a tool merely enabled,
 * or no tool at all — has nothing for the customer to do on the canvas this
 * turn, so the chat owns it.
 *
 * `finalizeFailed` is an explicit exception: FINALIZE_CANVAS hands over no
 * tool and sets neither flag, but a REJECTED finalize re-opens the canvas so
 * the customer can fix what the gate refused (see Surface.doRender's catch).
 * Reading the directive alone would point them at the chat while the thing
 * they must edit is on the canvas.
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
  return canvasDirective.showDone || canvasDirective.autoOpen !== null || finalizeFailed
    ? 'canvas'
    : 'chat'
}
