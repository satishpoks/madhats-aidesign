import { useEffect, useMemo, useState } from 'react'

interface ProductRefLike {
  name: string
  colour?: string
  reference_image_url: string
  view_images?: Record<string, string>
}

interface ProductViewerProps {
  productRef: ProductRefLike | null
  /** Generated (watermarked) design preview, shown as a tab once ready. */
  previewUrl?: string | null
}

const VIEW_ORDER = ['front', 'back', 'left', 'right'] as const

/**
 * Left pane of the studio: shows the product from up to four angles
 * (front / back / left / right) and, once a design is generated, a
 * "Your design" tab with the watermarked preview.
 */
export function ProductViewer({ productRef, previewUrl }: ProductViewerProps) {
  // Ordered list of [view, url] the product actually has.
  const views = useMemo(() => {
    const imgs = productRef?.view_images ?? {}
    const ordered = VIEW_ORDER.filter(v => imgs[v]).map(v => [v, imgs[v]] as const)
    if (ordered.length === 0 && productRef?.reference_image_url) {
      return [['front', productRef.reference_image_url] as const]
    }
    return ordered
  }, [productRef])

  const [active, setActive] = useState<string>('front')

  // Surface the generated design automatically the moment it's ready.
  useEffect(() => {
    if (previewUrl) setActive('design')
  }, [previewUrl])

  if (!productRef) {
    return (
      <div className="h-full flex items-center justify-center text-textMuted text-sm">
        Loading product…
      </div>
    )
  }

  // Prefer the generated design when present, else the first available view.
  const showingDesign = Boolean(previewUrl) && active === 'design'
  const activeView = views.find(([v]) => v === active)
  const mainSrc = showingDesign
    ? (previewUrl as string)
    : (activeView?.[1] ?? views[0]?.[1] ?? productRef.reference_image_url)

  return (
    <div className="h-full flex flex-col p-4 md:p-6 gap-4 bg-base">
      {/* Title */}
      <div>
        <h2 className="text-textPrimary font-semibold leading-tight">{productRef.name}</h2>
        {productRef.colour && (
          <p className="text-textMuted text-xs mt-0.5">{productRef.colour}</p>
        )}
      </div>

      {/* Main image */}
      <div className="flex-1 min-h-0 flex items-center justify-center bg-surface border border-border rounded-2xl overflow-hidden">
        <img
          src={mainSrc}
          alt={showingDesign ? 'Your generated design' : `${productRef.name} — ${active}`}
          className="max-h-full max-w-full object-contain"
        />
      </div>

      {showingDesign && (
        <p className="text-xs text-textMuted text-center -mt-2">
          Watermarked preview — reviewed by our team before quoting.
        </p>
      )}

      {/* Thumbnail strip: generated design (if any) + each available angle */}
      <div className="flex gap-2 flex-wrap justify-center flex-shrink-0">
        {previewUrl && (
          <Thumb
            label="Your design"
            src={previewUrl}
            selected={active === 'design'}
            onClick={() => setActive('design')}
          />
        )}
        {views.map(([view, src]) => (
          <Thumb
            key={view}
            label={view}
            src={src}
            selected={active === view}
            onClick={() => setActive(view)}
          />
        ))}
      </div>
    </div>
  )
}

interface ThumbProps {
  label: string
  src: string
  selected: boolean
  onClick: () => void
}

function Thumb({ label, src, selected, onClick }: ThumbProps) {
  return (
    <button
      onClick={onClick}
      aria-label={`Show ${label}`}
      title={label}
      className={`w-16 h-16 rounded-lg overflow-hidden border-2 bg-surface transition-colors ${
        selected ? 'border-accent' : 'border-border hover:border-textMuted'
      }`}
    >
      <img src={src} alt={label} className="w-full h-full object-cover" />
    </button>
  )
}
