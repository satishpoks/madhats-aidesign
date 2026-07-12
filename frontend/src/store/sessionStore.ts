import { create } from 'zustand'
import type { Product } from '../lib/types'
import { createSession, createBlankSession, fetchProduct, getSession, type HatType } from '../lib/api'
import { useChatStore } from './chatStore'

export type SessionView = 'picker' | 'session' | 'blank'

export interface ProductRef {
  id: string
  name: string
  colour: string
  style: string
  reference_image_url: string
  /** Keyed by view angle (e.g. 'front', 'back', 'left', 'right'). */
  view_images: Record<string, string>
}

/** URL query params captured at bootstrap time — available for analytics and later tasks. */
export interface EntryContext {
  variantId: string | null
  colour: string | null
  source: string | null
}

interface SessionState {
  sessionId: string | null
  shareToken: string | null
  state: string | null
  productRef: ProductRef | null
  /** Captures variant_id, colour, source from the Shopify embed URL at bootstrap time. */
  entryContext: EntryContext | null
  view: SessionView

  startSession: (product: Product) => Promise<void>
  startBlankSession: (hatType: HatType, colour: { name: string; hex: string }) => Promise<void>
  resumeSession: (token: string) => Promise<void>
  bootstrapFromUrl: () => Promise<void>
}

export const useSessionStore = create<SessionState>((set, get) => ({
  sessionId: null,
  shareToken: null,
  state: null,
  productRef: null,
  entryContext: null,
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
        view_images: product.view_images,
      },
      view: 'session',
    })
  },

  startBlankSession: async (hatType: HatType, colour: { name: string; hex: string }) => {
    const response = await createBlankSession(hatType.id, colour)
    set({
      sessionId: response.session_id,
      shareToken: response.share_token,
      state: response.state,
      // Populate the left-pane viewer from the chosen blank hat + colour.
      // Without this the ProductViewer stays on "Loading product…".
      productRef: {
        id: hatType.id,
        name: hatType.name,
        colour: colour.name,
        style: hatType.style,
        reference_image_url: hatType.view_images.front ?? '',
        view_images: hatType.view_images,
      },
      view: 'session',
    })
  },

  resumeSession: async (token: string) => {
    // Reopen an existing session (e.g. from the "make some edits" email link):
    // rehydrate the full chat thread, state and product so the customer picks
    // up exactly where they left off.
    const detail = await getSession(token)

    // product_ref persisted on the session omits view_images, so pull the full
    // product for the left-pane angles (best-effort — fall back to the ref).
    const ref = detail.product_ref ?? {}
    let productRef: ProductRef = {
      id: ref.product_id ?? '',
      name: ref.name ?? 'Your cap',
      colour: ref.colour ?? '',
      style: ref.style ?? '',
      reference_image_url: ref.reference_image_url ?? '',
      view_images: {},
    }
    if (ref.product_id) {
      try {
        const product = await fetchProduct(ref.product_id)
        productRef = {
          id: product.id,
          name: product.name,
          colour: product.colour,
          style: product.style,
          reference_image_url: product.reference_image_url,
          view_images: product.view_images,
        }
      } catch {
        // keep the ref-derived productRef
      }
    }

    set({
      sessionId: detail.session_id,
      shareToken: detail.share_token,
      state: detail.state,
      productRef,
      view: 'session',
    })
    useChatStore.getState().hydrate(detail.messages, detail.state, detail.data)
  },

  bootstrapFromUrl: async () => {
    const params = new URLSearchParams(window.location.search)

    // Resume link (from the preview email's "make some edits" CTA) wins.
    const resumeToken = params.get('session')
    if (resumeToken) {
      try {
        await get().resumeSession(resumeToken)
        return
      } catch (err) {
        console.warn('[MadHats] resumeSession failed — falling back', err)
      }
    }

    if (params.get('mode') === 'blank') {
      set({ view: 'blank' })
      return
    }

    const productId = params.get('product_id')
    if (!productId) return

    const variantId = params.get('variant_id')
    const colour = params.get('colour')
    const source = params.get('source')

    try {
      const product = await fetchProduct(productId)
      await get().startSession(product)
      set({ entryContext: { variantId, colour, source } })
    } catch (err) {
      // If bootstrap fails (product not found, backend down, etc.) stay at picker.
      // Warn so a broken Shopify embed URL is diagnosable in the browser console.
      console.warn('[MadHats] bootstrapFromUrl failed — staying at picker', err)
    }
  },
}))
