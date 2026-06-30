import { create } from 'zustand'
import type { Product } from '../lib/types'
import { createSession, fetchProduct } from '../lib/api'

export type SessionView = 'picker' | 'session'

export interface ProductRef {
  id: string
  name: string
  colour: string
  style: string
  reference_image_url: string
}

interface SessionState {
  sessionId: string | null
  shareToken: string | null
  state: string | null
  productRef: ProductRef | null
  view: SessionView

  startSession: (product: Product) => Promise<void>
  bootstrapFromUrl: () => Promise<void>
}

export const useSessionStore = create<SessionState>((set, get) => ({
  sessionId: null,
  shareToken: null,
  state: null,
  productRef: null,
  view: 'picker',

  startSession: async (product: Product) => {
    const response = await createSession(product.id)
    set({
      sessionId: response.session_id,
      shareToken: response.share_token,
      state: response.state,
      productRef: {
        id: product.id,
        name: product.name,
        colour: product.colour,
        style: product.style,
        reference_image_url: product.reference_image_url,
      },
      view: 'session',
    })
  },

  bootstrapFromUrl: async () => {
    const params = new URLSearchParams(window.location.search)
    const productId = params.get('product_id')
    // Future: params.get('variant_id'), params.get('colour'), params.get('source')
    if (!productId) return

    try {
      const product = await fetchProduct(productId)
      await get().startSession(product)
    } catch {
      // If bootstrap fails (product not found, backend down, etc.) stay at picker
    }
  },
}))
