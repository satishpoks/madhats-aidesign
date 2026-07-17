import { create } from 'zustand'

export type Face = 'front' | 'back' | 'left' | 'right'
export const FACES: Face[] = ['front', 'back', 'left', 'right']

/** Built-in vector shapes (the "Clipart" palette) — recolourable, not images. */
export type ShapeKind =
  | 'rect' | 'square' | 'roundedRect'
  | 'circle' | 'ellipse'
  | 'triangle' | 'diamond' | 'pentagon' | 'hexagon' | 'star'
  | 'line' | 'arrow' | 'doubleArrow'

/** Line-like shapes have no fill/outline concept — a single colour + width. */
export const LINE_SHAPES: ShapeKind[] = ['line', 'arrow', 'doubleArrow']

export interface CanvasElement {
  id: string
  type: 'text' | 'image' | 'shape' | 'drawing'
  x: number; y: number; width: number; height: number; rotation: number
  zIndex: number
  content?: string; font?: string; colour?: string; fontSize?: number
  /** Text arch: 0 = straight, negative = arch down, positive = arch up. */
  curve?: number
  assetUrl?: string; removeBg?: boolean
  /** Original (pre-background-removal) asset URL, so the toggle is reversible. */
  originalAssetUrl?: string
  /** Freehand drawing: flat list of normalised x,y pairs [x0,y0,x1,y1,…]. */
  points?: number[]
  // shape
  shapeKind?: ShapeKind
  fill?: string
  stroke?: string
  strokeWidth?: number
  filled?: boolean
  /** v2 flow: a locked layer can't be moved/resized/selected. */
  locked?: boolean
}

export interface Colourway { name: string; hex: string }

export interface CanvasDesign {
  colourway: Colourway | null
  faces: Record<Face, CanvasElement[]>
}

interface CanvasState {
  faces: Record<Face, CanvasElement[]>
  activeFace: Face
  selectedId: string | null
  colourway: Colourway | null
  faceImages: Record<Face, string>
  drawMode: boolean
  drawColour: string
  drawWidth: number

  setFaceImages: (imgs: Partial<Record<Face, string>>) => void
  setActiveFace: (f: Face) => void
  addText: (text: string) => void
  /** aspect = naturalWidth / naturalHeight; the element is inserted undistorted. */
  addImage: (assetUrl: string, aspect?: number) => void
  addShape: (kind: ShapeKind) => void
  updateElement: (id: string, patch: Partial<CanvasElement>) => void
  duplicate: (id: string) => void
  removeElement: (id: string) => void
  reorder: (id: string, dir: 'up' | 'down') => void
  select: (id: string | null) => void
  setColourway: (c: Colourway | null) => void
  setDrawMode: (v: boolean) => void
  setDrawColour: (c: string) => void
  setDrawWidth: (w: number) => void
  addDrawing: (points: number[]) => void
  lockAll: () => void
  /** v2: lock every currently-unlocked element (across all faces). Since each
   *  step adds an element then locks, "lock all unlocked" == "lock the one
   *  just placed" without needing to track which element that was. */
  lockPlaced: () => void
  /** Ops channel: patch by explicit face — `updateElement` only sees activeFace. */
  patchElement: (face: Face, id: string, patch: Partial<CanvasElement>) => void
  removeElementOn: (face: Face, id: string) => void
  /** Patch the last unlocked image on `face` — the logo just placed. Same
   *  "last unlocked" anchor `lockPlaced` uses, because the backend has no id
   *  for it: canvas_design isn't persisted until finalize. */
  patchPendingLogo: (face: Face, patch: Partial<CanvasElement>) => void
  reset: () => void
  toCanvasDesign: () => CanvasDesign
  /** Load a persisted design back onto the canvas (resuming from the email "edit" link). */
  fromCanvasDesign: (design: CanvasDesign | null | undefined) => void
}

const emptyFaces = (): Record<Face, CanvasElement[]> => ({ front: [], back: [], left: [], right: [] })
const uid = () => Math.random().toString(36).slice(2, 10)

export const useCanvasStore = create<CanvasState>((set, get) => ({
  faces: emptyFaces(),
  activeFace: 'front',
  selectedId: null,
  colourway: null,
  faceImages: { front: '', back: '', left: '', right: '' },
  drawMode: false,
  drawColour: '#111827',
  drawWidth: 0.01,

  setFaceImages: imgs => set(s => ({ faceImages: { ...s.faceImages, ...imgs } })),
  setActiveFace: f => set({ activeFace: f, selectedId: null }),

  addText: text => set(s => {
    const el: CanvasElement = {
      id: uid(), type: 'text', x: 0.5, y: 0.4, width: 0.3, height: 0.12,
      rotation: 0, zIndex: s.faces[s.activeFace].length,
      content: text, font: 'Arial', fontSize: 36,
    }
    return { faces: { ...s.faces, [s.activeFace]: [...s.faces[s.activeFace], el] }, selectedId: el.id }
  }),

  addImage: (assetUrl, aspect = 1) => set(s => {
    // Fit inside a 0.4×0.4 (normalised) box while preserving the image's aspect
    // ratio, so it inserts undistorted; the stage is square so normalised w/h
    // map directly to the visual ratio. The user can freely resize afterwards.
    const a = aspect && isFinite(aspect) && aspect > 0 ? aspect : 1
    const maxN = 0.4
    const width = a >= 1 ? maxN : maxN * a
    const height = a >= 1 ? maxN / a : maxN
    const el: CanvasElement = {
      id: uid(), type: 'image', x: 0.5 - width / 2, y: 0.5 - height / 2, width, height,
      rotation: 0, zIndex: s.faces[s.activeFace].length, assetUrl, removeBg: false,
    }
    return { faces: { ...s.faces, [s.activeFace]: [...s.faces[s.activeFace], el] }, selectedId: el.id }
  }),

  addShape: kind => set(s => {
    // Square/circle insert as an equal-sided box; others fit a 0.3×0.3 box.
    const size = 0.3
    const isEqual = kind === 'square' || kind === 'circle'
    const width = size
    const height = isEqual ? size : kind === 'line' || kind === 'arrow' || kind === 'doubleArrow' ? 0.06 : size
    const el: CanvasElement = {
      id: uid(), type: 'shape', shapeKind: kind,
      x: 0.5 - width / 2, y: 0.5 - height / 2, width, height,
      rotation: 0, zIndex: s.faces[s.activeFace].length,
      fill: '#2563eb', stroke: '#111827', strokeWidth: LINE_SHAPES.includes(kind) ? 6 : 0, filled: true,
    }
    return { faces: { ...s.faces, [s.activeFace]: [...s.faces[s.activeFace], el] }, selectedId: el.id }
  }),

  updateElement: (id, patch) => set(s => ({
    faces: {
      ...s.faces,
      [s.activeFace]: s.faces[s.activeFace].map(e => (e.id === id ? { ...e, ...patch } : e)),
    },
  })),

  duplicate: id => set(s => {
    const arr = s.faces[s.activeFace]
    const src = arr.find(e => e.id === id)
    if (!src) return s
    // Clone with a new id, nudged down-right so the copy is visible, stacked on top.
    const copy: CanvasElement = {
      ...src,
      id: uid(),
      x: Math.min(src.x + 0.04, 0.9),
      y: Math.min(src.y + 0.04, 0.9),
      zIndex: arr.length,
    }
    return { faces: { ...s.faces, [s.activeFace]: [...arr, copy] }, selectedId: copy.id }
  }),

  removeElement: id => set(s => ({
    faces: { ...s.faces, [s.activeFace]: s.faces[s.activeFace].filter(e => e.id !== id) },
    selectedId: s.selectedId === id ? null : s.selectedId,
  })),

  patchElement: (face, id, patch) => set(s => ({
    faces: { ...s.faces, [face]: s.faces[face].map(e => (e.id === id ? { ...e, ...patch } : e)) },
  })),

  removeElementOn: (face, id) => set(s => ({
    faces: { ...s.faces, [face]: s.faces[face].filter(e => e.id !== id) },
  })),

  patchPendingLogo: (face, patch) => set(s => {
    const arr = s.faces[face]
    let idx = -1
    for (let i = arr.length - 1; i >= 0; i--) {
      if (arr[i].type === 'image' && !arr[i].locked) { idx = i; break }
    }
    if (idx === -1) return s
    const next = arr.slice()
    next[idx] = { ...next[idx], ...patch }
    return { faces: { ...s.faces, [face]: next } }
  }),

  reorder: (id, dir) => set(s => {
    const arr = [...s.faces[s.activeFace]]
    const i = arr.findIndex(e => e.id === id)
    const j = dir === 'up' ? i + 1 : i - 1
    if (i < 0 || j < 0 || j >= arr.length) return s
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
    arr.forEach((e, k) => (e.zIndex = k))
    return { faces: { ...s.faces, [s.activeFace]: arr } }
  }),

  select: id => set({ selectedId: id }),
  setColourway: c => set({ colourway: c }),
  setDrawMode: v => set({ drawMode: v, selectedId: null }),
  setDrawColour: c => set({ drawColour: c }),
  setDrawWidth: w => set({ drawWidth: w }),

  addDrawing: points => set(s => {
    const el: CanvasElement = {
      id: uid(), type: 'drawing', x: 0, y: 0, width: 0, height: 0, rotation: 0,
      zIndex: s.faces[s.activeFace].length,
      points, stroke: s.drawColour, strokeWidth: s.drawWidth,
    }
    // Exit draw mode on commit so the just-drawn stroke is immediately
    // selectable/movable — while drawMode is on, CanvasStage disables layer
    // listening and no element (including this one) can be clicked.
    return { faces: { ...s.faces, [s.activeFace]: [...s.faces[s.activeFace], el] }, selectedId: el.id, drawMode: false }
  }),

  lockAll: () => set(s => {
    const faces = { ...s.faces }
    for (const f of FACES) faces[f] = faces[f].map(e => ({ ...e, locked: true }))
    return { faces, selectedId: null }
  }),

  lockPlaced: () => set(s => {
    const faces = { ...s.faces }
    for (const f of FACES) {
      faces[f] = faces[f].map(e => (e.locked ? e : { ...e, locked: true }))
    }
    return { faces, selectedId: null }
  }),

  reset: () => set({ faces: emptyFaces(), activeFace: 'front', selectedId: null, colourway: null,
    faceImages: { front: '', back: '', left: '', right: '' },
    drawMode: false, drawColour: '#111827', drawWidth: 0.01 }),

  toCanvasDesign: () => {
    const { faces, colourway } = get()
    return { colourway, faces }
  },

  fromCanvasDesign: design => set(() => {
    // Merge onto a full empty-faces base so a partial/legacy blob (missing a
    // face key) still yields a valid Record<Face, …> and never throws downstream.
    const faces = { ...emptyFaces(), ...(design?.faces ?? {}) }
    return {
      faces,
      colourway: design?.colourway ?? null,
      activeFace: 'front' as Face,
      selectedId: null,
    }
  }),
}))
