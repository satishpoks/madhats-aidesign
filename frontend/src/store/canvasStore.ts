import { create } from 'zustand'

export type Face = 'front' | 'back' | 'left' | 'right'
export const FACES: Face[] = ['front', 'back', 'left', 'right']

export interface CanvasElement {
  id: string
  type: 'text' | 'image'
  x: number; y: number; width: number; height: number; rotation: number
  zIndex: number
  content?: string; font?: string; colour?: string; fontSize?: number
  assetUrl?: string; removeBg?: boolean
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

  setFaceImages: (imgs: Partial<Record<Face, string>>) => void
  setActiveFace: (f: Face) => void
  addText: (text: string) => void
  addImage: (assetUrl: string) => void
  updateElement: (id: string, patch: Partial<CanvasElement>) => void
  removeElement: (id: string) => void
  reorder: (id: string, dir: 'up' | 'down') => void
  select: (id: string | null) => void
  setColourway: (c: Colourway | null) => void
  reset: () => void
  toCanvasDesign: () => CanvasDesign
}

const emptyFaces = (): Record<Face, CanvasElement[]> => ({ front: [], back: [], left: [], right: [] })
const uid = () => Math.random().toString(36).slice(2, 10)

export const useCanvasStore = create<CanvasState>((set, get) => ({
  faces: emptyFaces(),
  activeFace: 'front',
  selectedId: null,
  colourway: null,
  faceImages: { front: '', back: '', left: '', right: '' },

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

  addImage: assetUrl => set(s => {
    const el: CanvasElement = {
      id: uid(), type: 'image', x: 0.5, y: 0.5, width: 0.35, height: 0.35,
      rotation: 0, zIndex: s.faces[s.activeFace].length, assetUrl, removeBg: false,
    }
    return { faces: { ...s.faces, [s.activeFace]: [...s.faces[s.activeFace], el] }, selectedId: el.id }
  }),

  updateElement: (id, patch) => set(s => ({
    faces: {
      ...s.faces,
      [s.activeFace]: s.faces[s.activeFace].map(e => (e.id === id ? { ...e, ...patch } : e)),
    },
  })),

  removeElement: id => set(s => ({
    faces: { ...s.faces, [s.activeFace]: s.faces[s.activeFace].filter(e => e.id !== id) },
    selectedId: s.selectedId === id ? null : s.selectedId,
  })),

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
  reset: () => set({ faces: emptyFaces(), activeFace: 'front', selectedId: null, colourway: null,
    faceImages: { front: '', back: '', left: '', right: '' } }),

  toCanvasDesign: () => {
    const { faces, colourway } = get()
    return { colourway, faces }
  },
}))
