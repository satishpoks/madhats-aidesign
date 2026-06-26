import { create } from 'zustand'
import type { Product, ColourSwatch, PlacementZone, DecorationStyle } from '../data/products'

export type View = 'picker' | 'studio' | 'refine' | 'worn'
export type AngleView = 'front' | 'left' | 'right' | 'back'
type InputTab = 'describe' | 'upload'
type GenerationState = 'idle' | 'generating' | 'done' | 'error'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  imageUrl?: string
  latency?: number
}

export type ViewImages = Record<AngleView, string | null>

interface StudioState {
  view: View
  selectedProduct: Product | null
  selectedSwatch: ColourSwatch | null
  inputTab: InputTab
  promptText: string
  uploadedFile: File | null
  uploadedPreview: string | null
  placementZone: PlacementZone
  decorationStyle: DecorationStyle
  generationState: GenerationState
  // 4-angle cap views
  viewImages: ViewImages
  activeAngle: AngleView
  // worn mockups
  wornImages: ViewImages
  isGeneratingWorn: boolean
  // meta
  generationMeta: { model: string; latency: number; tier: string } | null
  showConceptModal: boolean
  // chat
  messages: ChatMessage[]
  refineText: string
  isRefining: boolean

  selectProduct: (product: Product, swatch: ColourSwatch) => void
  setView: (view: View) => void
  setInputTab: (tab: InputTab) => void
  setPromptText: (text: string) => void
  setUploadedFile: (file: File, preview: string) => void
  setPlacementZone: (zone: PlacementZone) => void
  setDecorationStyle: (style: DecorationStyle) => void
  setActiveAngle: (angle: AngleView) => void
  triggerGenerate: () => Promise<void>
  triggerRefine: (text: string) => Promise<void>
  triggerGenerateWorn: () => Promise<void>
  setRefineText: (text: string) => void
  setShowConceptModal: (show: boolean) => void
  reset: () => void
}

// Different cap angles — in production these come from the AI model
const CAP_STUBS: ViewImages[] = [
  {
    front: 'https://images.unsplash.com/photo-1588850561407-ed78c282e89b?w=600&q=80',
    left:  'https://images.unsplash.com/photo-1556306535-0f09a537f0a3?w=600&q=80',
    right: 'https://images.unsplash.com/photo-1521369909029-2afed882baee?w=600&q=80',
    back:  'https://images.unsplash.com/photo-1534215754734-18e55d13e346?w=600&q=80',
  },
  {
    front: 'https://images.unsplash.com/photo-1521369909029-2afed882baee?w=600&q=80',
    left:  'https://images.unsplash.com/photo-1588850561407-ed78c282e89b?w=600&q=80',
    right: 'https://images.unsplash.com/photo-1534215754734-18e55d13e346?w=600&q=80',
    back:  'https://images.unsplash.com/photo-1556306535-0f09a537f0a3?w=600&q=80',
  },
]

// Person wearing cap — lifestyle shots for Flow C
const WORN_STUBS: ViewImages[] = [
  {
    front: 'https://images.unsplash.com/photo-1503342217505-b0a15ec3261c?w=600&q=80',
    left:  'https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=600&q=80',
    right: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=600&q=80',
    back:  'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=600&q=80',
  },
]

const EMPTY_VIEWS: ViewImages = { front: null, left: null, right: null, back: null }

function uid() { return Math.random().toString(36).slice(2) }
function pick<T>(arr: T[]) { return arr[Math.floor(Math.random() * arr.length)] }

export const useStudioStore = create<StudioState>((set, get) => ({
  view: 'picker',
  selectedProduct: null,
  selectedSwatch: null,
  inputTab: 'describe',
  promptText: '',
  uploadedFile: null,
  uploadedPreview: null,
  placementZone: 'front',
  decorationStyle: 'embroidery',
  generationState: 'idle',
  viewImages: { ...EMPTY_VIEWS },
  activeAngle: 'front',
  wornImages: { ...EMPTY_VIEWS },
  isGeneratingWorn: false,
  generationMeta: null,
  showConceptModal: false,
  messages: [],
  refineText: '',
  isRefining: false,

  selectProduct: (product, swatch) => set({ selectedProduct: product, selectedSwatch: swatch }),
  setView: (view) => set({ view }),
  setInputTab: (tab) => set({ inputTab: tab }),
  setPromptText: (text) => set({ promptText: text }),
  setUploadedFile: (file, preview) => set({ uploadedFile: file, uploadedPreview: preview }),
  setPlacementZone: (zone) => set({ placementZone: zone }),
  setDecorationStyle: (style) => set({ decorationStyle: style }),
  setActiveAngle: (angle) => set({ activeAngle: angle }),
  setShowConceptModal: (show) => set({ showConceptModal: show }),
  setRefineText: (text) => set({ refineText: text }),

  triggerGenerate: async () => {
    const { inputTab, promptText, uploadedFile } = get()
    if (inputTab === 'describe' && !promptText.trim()) return
    if (inputTab === 'upload' && !uploadedFile) return

    set({
      generationState: 'generating',
      viewImages: { ...EMPTY_VIEWS },
      wornImages: { ...EMPTY_VIEWS },
      messages: [],
      activeAngle: 'front',
    })
    const start = Date.now()

    // stagger the 4 views arriving — front first, then sides, then back
    const views = pick(CAP_STUBS)
    await new Promise(r => setTimeout(r, 1200))
    set(s => ({ viewImages: { ...s.viewImages, front: views.front } }))
    await new Promise(r => setTimeout(r, 600))
    set(s => ({ viewImages: { ...s.viewImages, left: views.left, right: views.right } }))
    await new Promise(r => setTimeout(r, 600))
    set(s => ({ viewImages: { ...s.viewImages, back: views.back } }))

    const latency = Date.now() - start
    const userText = inputTab === 'describe' ? promptText : `Uploaded: ${uploadedFile!.name}`

    set({
      view: 'refine',
      generationState: 'done',
      generationMeta: { model: 'gemini-flash-preview', latency, tier: 'preview' },
      messages: [
        { id: uid(), role: 'user', text: userText },
        { id: uid(), role: 'assistant', text: 'Preview generated from 4 angles. What would you like to change?', imageUrl: views.front ?? undefined, latency },
      ],
    })
  },

  triggerRefine: async (text: string) => {
    if (!text.trim()) return
    set(s => ({
      isRefining: true,
      refineText: '',
      viewImages: { ...EMPTY_VIEWS },
      messages: [...s.messages, { id: uid(), role: 'user', text }],
    }))

    const start = Date.now()
    const views = pick(CAP_STUBS)

    await new Promise(r => setTimeout(r, 1000))
    set(s => ({ viewImages: { ...s.viewImages, front: views.front } }))
    await new Promise(r => setTimeout(r, 500))
    set(s => ({ viewImages: { ...s.viewImages, left: views.left, right: views.right } }))
    await new Promise(r => setTimeout(r, 500))
    set(s => ({ viewImages: { ...s.viewImages, back: views.back } }))

    const latency = Date.now() - start

    set(s => ({
      isRefining: false,
      generationMeta: { model: 'gemini-flash-preview', latency, tier: 'preview' },
      messages: [
        ...s.messages,
        { id: uid(), role: 'assistant', text: 'Updated all 4 views. Anything else?', imageUrl: views.front ?? undefined, latency },
      ],
    }))
  },

  triggerGenerateWorn: async () => {
    set({ isGeneratingWorn: true, wornImages: { ...EMPTY_VIEWS }, view: 'worn' })

    const worn = pick(WORN_STUBS)
    await new Promise(r => setTimeout(r, 1200))
    set(s => ({ wornImages: { ...s.wornImages, front: worn.front } }))
    await new Promise(r => setTimeout(r, 700))
    set(s => ({ wornImages: { ...s.wornImages, left: worn.left } }))
    await new Promise(r => setTimeout(r, 700))
    set(s => ({ wornImages: { ...s.wornImages, right: worn.right } }))
    await new Promise(r => setTimeout(r, 700))
    set(s => ({ wornImages: { ...s.wornImages, back: worn.back } }))

    set({ isGeneratingWorn: false })
  },

  reset: () => set({
    view: 'picker',
    selectedProduct: null,
    selectedSwatch: null,
    promptText: '',
    uploadedFile: null,
    uploadedPreview: null,
    generationState: 'idle',
    viewImages: { ...EMPTY_VIEWS },
    activeAngle: 'front',
    wornImages: { ...EMPTY_VIEWS },
    isGeneratingWorn: false,
    generationMeta: null,
    showConceptModal: false,
    messages: [],
    refineText: '',
    isRefining: false,
  }),
}))
