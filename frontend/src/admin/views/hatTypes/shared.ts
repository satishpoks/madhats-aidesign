import { useEffect, useState } from 'react'
import { listStores, type HatType, type Store } from '../../adminApi'

export const VIEWS = ['front', 'back', 'left', 'right'] as const
export type View = (typeof VIEWS)[number]

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

type AngleShape = Pick<HatType, 'blank_view_images'>

export function angleCount(h: AngleShape): number {
  return VIEWS.filter((v) => h.blank_view_images[v]).length
}

export function allAngles(h: AngleShape): boolean {
  return angleCount(h) === VIEWS.length
}

export type HatStatus = 'active' | 'draft' | 'needs_images'

export function hatStatus(h: Pick<HatType, 'blank_view_images' | 'active'>): HatStatus {
  if (!allAngles(h)) return 'needs_images'
  return h.active ? 'active' : 'draft'
}

export function useStores(): { stores: Store[]; loading: boolean; error: string | null } {
  const [stores, setStores] = useState<Store[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let active = true
    listStores()
      .then((data) => {
        if (active) {
          setStores(data)
          setError(null)
        }
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : 'Failed to load stores')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])
  return { stores, loading, error }
}
