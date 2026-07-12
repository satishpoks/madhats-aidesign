import { useEffect, useMemo, useState } from 'react'

interface ProductRefLike {
  name: string
  colour?: string
  reference_image_url: string
  view_images?: Record<string, string>
}

interface ProductViewerProps {
  productRef: ProductRefLike | null
  /** Watermarked design images (newest last). Shown once released. */
  designUrls?: string[]
  /**
   * Composited blank-hat views (front/back/left/right), from the composite
   * endpoint. When present, back/left/right prefer these over the blank
   * product-reference angle photos; front keeps the AI hero (design/reference)
   * unchanged. Absent for the customise flow — behaviour there is untouched.
   */
  compositeViews?: Record<string, string>
}

const VIEW_ORDER = ['front', 'back', 'left', 'right'] as const

interface Thumb {
  key: string
  label: string
  src: string
}

export function ProductViewer({ productRef, designUrls = [], compositeViews }: ProductViewerProps) {
  const angleThumbs = useMemo<Thumb[]>(() => {
    const imgs = productRef?.view_images ?? {}
    const ordered = VIEW_ORDER.filter(v => imgs[v]).map(v => ({
      key: v,
      label: v,
      // Front keeps the AI hero (blank reference / design thumbs win via
      // ordering below); back/left/right prefer the composited view when available.
      src: v !== 'front' && compositeViews?.[v] ? compositeViews[v] : imgs[v],
    }))
    if (ordered.length === 0 && productRef?.reference_image_url) {
      return [{ key: 'front', label: 'front', src: productRef.reference_image_url }]
    }
    return ordered
  }, [productRef, compositeViews])

  const designThumbs = useMemo<Thumb[]>(
    () => designUrls.map((src, i) => ({ key: `design-${i}`, label: designUrls.length > 1 ? `design ${i + 1}` : 'design', src })),
    [designUrls],
  )

  // Design thumbs first (newest design is the initial main image).
  const thumbs = useMemo<Thumb[]>(() => [...designThumbs, ...angleThumbs], [designThumbs, angleThumbs])
  const defaultKey = designThumbs.length ? designThumbs[designThumbs.length - 1].key : angleThumbs[0]?.key ?? ''
  const [activeKey, setActiveKey] = useState(defaultKey)

  // When a new design arrives, promote it to the main view.
  useEffect(() => {
    if (designThumbs.length) setActiveKey(designThumbs[designThumbs.length - 1].key)
  }, [designThumbs.length])

  if (!productRef) {
    return (
      <div className="h-full flex items-center justify-center text-textMuted text-sm bg-base">
        Loading product…
      </div>
    )
  }

  const active = thumbs.find(t => t.key === activeKey) ?? thumbs[0]

  return (
    <div className="h-full flex flex-col p-4 md:p-6 gap-4 bg-base overflow-y-auto">
      <div className="flex-shrink-0">
        <h2 className="text-textPrimary font-semibold leading-tight">
          {productRef.name}
          {productRef.colour && <span className="text-textSub"> — {productRef.colour}</span>}
        </h2>
        <p className="text-textMuted text-xs mt-0.5">
          {designThumbs.length ? 'Your design — tap a thumbnail to compare angles' : 'Choose a view to explore your cap'}
        </p>
      </div>

      {/* Main image */}
      <div className="flex-1 min-h-0 flex items-center justify-center rounded-2xl bg-surface border-2 border-border p-4">
        {active && (
          <img src={active.src} alt="main view" className="max-h-full max-w-full object-contain" draggable={false} />
        )}
      </div>

      {/* Thumbnail strip */}
      <div className="flex-shrink-0 flex gap-3 overflow-x-auto pb-1">
        {thumbs.map(t => (
          <button
            key={t.key}
            onClick={() => setActiveKey(t.key)}
            aria-label={`Show ${t.label}`}
            aria-pressed={activeKey === t.key}
            title={t.label}
            className={`group relative flex-shrink-0 w-20 h-20 rounded-xl bg-surface p-1.5 transition-colors ${
              activeKey === t.key ? 'border-2 border-accent' : 'border-2 border-border hover:border-textMuted'
            }`}
          >
            <img src={t.src} alt={t.label} className="w-full h-full object-contain" draggable={false} />
          </button>
        ))}
      </div>
    </div>
  )
}
