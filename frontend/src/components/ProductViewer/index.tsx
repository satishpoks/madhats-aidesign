import { useEffect, useMemo, useState } from 'react'

interface ProductRefLike {
  name: string
  colour?: string
  reference_image_url: string
  view_images?: Record<string, string>
}

interface ProductViewerProps {
  productRef: ProductRefLike | null
  /** Generated (watermarked) design preview, shown as a card once ready. */
  previewUrl?: string | null
}

const VIEW_ORDER = ['front', 'back', 'left', 'right'] as const

/**
 * Left pane of the studio (per Figma "02 — Chatbot Screens"): a 2×2 grid of
 * view cards — front / back / left / right — each with a pill label; the
 * selected view is outlined in accent. Once a design is generated a "Your
 * design" card is prepended.
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
      <div className="h-full flex items-center justify-center text-textMuted text-sm bg-base">
        Loading product…
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col p-4 md:p-6 gap-4 bg-base overflow-y-auto">
      {/* Title + prompt */}
      <div className="flex-shrink-0">
        <h2 className="text-textPrimary font-semibold leading-tight">
          {productRef.name}
          {productRef.colour && <span className="text-textSub"> — {productRef.colour}</span>}
        </h2>
        <p className="text-textMuted text-xs mt-0.5">Choose a view to explore your cap</p>
      </div>

      {/* 2×2 grid of view cards (+ optional generated design card) */}
      <div className="grid grid-cols-2 gap-4 flex-1 min-h-0 auto-rows-fr">
        {previewUrl && (
          <ViewCard
            label="Your design"
            src={previewUrl}
            selected={active === 'design'}
            onClick={() => setActive('design')}
          />
        )}
        {views.map(([view, src]) => (
          <ViewCard
            key={view}
            label={view}
            src={src}
            selected={active === view}
            onClick={() => setActive(view)}
          />
        ))}
      </div>

      {/* Footer note */}
      <p className="text-xs text-textMuted flex-shrink-0">
        Your design will be emailed to you once email is verified
      </p>
    </div>
  )
}

interface ViewCardProps {
  label: string
  src: string
  selected: boolean
  onClick: () => void
}

function ViewCard({ label, src, selected, onClick }: ViewCardProps) {
  return (
    <button
      onClick={onClick}
      aria-label={`Show ${label}`}
      aria-pressed={selected}
      title={label}
      className={`group relative flex flex-col items-center justify-center gap-3 rounded-2xl bg-surface p-4 transition-colors ${
        selected
          ? 'border-2 border-accent shadow-sm'
          : 'border-2 border-border hover:border-textMuted'
      }`}
    >
      <img
        src={src}
        alt={label}
        className="max-h-[75%] max-w-full object-contain"
        draggable={false}
      />
      <span
        className={`mt-auto px-4 py-1 rounded-full text-sm font-medium capitalize transition-colors ${
          selected
            ? 'border border-accent text-accent bg-surface'
            : 'border border-transparent bg-base text-textMuted group-hover:text-textSub'
        }`}
      >
        {label}
      </span>
    </button>
  )
}
