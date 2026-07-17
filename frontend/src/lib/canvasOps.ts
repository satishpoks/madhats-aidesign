import { useCanvasStore, FACES, type CanvasElement, type Face } from '../store/canvasStore'

export type CanvasOpTarget =
  | { kind: 'element'; id: string; face: Face }
  | { kind: 'pending_logo'; face: Face }

export interface CanvasOp {
  target: CanvasOpTarget
  patch?: Partial<CanvasElement>
  remove?: boolean
}

function isFace(v: unknown): v is Face {
  return typeof v === 'string' && (FACES as string[]).includes(v)
}

/** Ops are already fully resolved by the backend (arithmetic, clamping, colour
 *  names). This only rejects structurally invalid rows. */
export function parseCanvasOps(data: Record<string, unknown>): CanvasOp[] {
  if (!Array.isArray(data.canvas_ops)) return []
  const out: CanvasOp[] = []
  for (const raw of data.canvas_ops as unknown[]) {
    if (!raw || typeof raw !== 'object') continue
    const op = raw as Record<string, unknown>
    const t = op.target as Record<string, unknown> | undefined
    if (!t || !isFace(t.face)) continue
    if (t.kind === 'pending_logo') {
      out.push({ target: { kind: 'pending_logo', face: t.face }, patch: op.patch as Partial<CanvasElement>, remove: op.remove === true })
    } else if (t.kind === 'element' && typeof t.id === 'string') {
      out.push({ target: { kind: 'element', id: t.id, face: t.face }, patch: op.patch as Partial<CanvasElement>, remove: op.remove === true })
    }
  }
  return out
}

/** Applied imperatively where the response lands — NOT in a React effect.
 *  An effect fires on change, which would re-apply on resume/hydrate and
 *  re-flag the wrong logo on a later loop pass. */
export function applyCanvasOps(ops: CanvasOp[]): void {
  if (!ops.length) return
  const s = useCanvasStore.getState()
  for (const op of ops) {
    if (op.target.kind === 'pending_logo') {
      if (op.patch) s.patchPendingLogo(op.target.face, op.patch)
      continue
    }
    if (op.remove) s.removeElementOn(op.target.face, op.target.id)
    else if (op.patch) s.patchElement(op.target.face, op.target.id, op.patch)
  }
}
