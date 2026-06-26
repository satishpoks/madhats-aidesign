import { useState } from 'react'
import { PRODUCTS } from '../../data/products'
import type { Product, ColourSwatch } from '../../data/products'
import { useStudioStore } from '../../store/studioStore'
import { CapSilhouette } from './CapSilhouette'

export function ProductPicker() {
  const { selectProduct, setView } = useStudioStore()
  const [hoveredSwatch, setHoveredSwatch] = useState<Record<string, string>>({})

  function getColour(product: Product) {
    return hoveredSwatch[product.id] ?? product.defaultColour
  }

  function handleSelect(product: Product, swatch: ColourSwatch) {
    selectProduct(product, swatch)
    setView('studio')
  }

  return (
    <div className="min-h-screen bg-base flex flex-col">
      {/* Header */}
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-accent font-bold text-xl tracking-tight">MadHats</span>
          <span className="text-border text-xl">|</span>
          <span className="text-textSub text-sm font-medium">AI Design Studio</span>
        </div>
        <span className="text-xs text-textMuted bg-surface border border-border px-3 py-1 rounded-full">
          Beta Preview
        </span>
      </header>

      {/* Hero */}
      <div className="text-center pt-12 pb-8 px-4">
        <h1 className="text-3xl font-bold text-textPrimary mb-2">
          Design your cap, <span className="text-accent">instantly.</span>
        </h1>
        <p className="text-textMuted text-base max-w-lg mx-auto">
          Pick a style, describe your idea or upload a logo — and see it on the cap in seconds.
        </p>
        <button className="mt-4 text-sm text-accent underline underline-offset-2 hover:text-accentHover transition-colors">
          Describe your idea instead →
        </button>
      </div>

      {/* Product Grid */}
      <div className="px-6 pb-12">
        <p className="text-xs text-textMuted uppercase tracking-widest mb-4 font-medium">
          Choose a style
        </p>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {PRODUCTS.map((product) => {
            const colour = getColour(product)
            const swatch = product.swatches.find(s => s.hex === colour) ?? product.swatches[0]

            return (
              <div
                key={product.id}
                onClick={() => handleSelect(product, swatch)}
                className="bg-surface border border-border rounded-2xl p-4 cursor-pointer group hover:border-accent transition-all duration-200 hover:shadow-[0_0_0_1px_#FF5C00]"
              >
                {/* Silhouette */}
                <div className="aspect-square w-full flex items-center justify-center mb-3 px-2">
                  <CapSilhouette style={product.style} colour={colour} />
                </div>

                {/* Info */}
                <div className="space-y-1 mb-3">
                  <p className="text-textPrimary text-sm font-semibold leading-tight">{product.name}</p>
                  <p className="text-textMuted text-xs">{product.brand}</p>
                </div>

                {/* Swatches */}
                <div className="flex gap-1.5 flex-wrap">
                  {product.swatches.map((sw) => (
                    <button
                      key={sw.hex}
                      title={sw.name}
                      onClick={(e) => {
                        e.stopPropagation()
                        setHoveredSwatch(prev => ({ ...prev, [product.id]: sw.hex }))
                      }}
                      className="w-4 h-4 rounded-full border-2 transition-all"
                      style={{
                        backgroundColor: sw.hex,
                        borderColor: colour === sw.hex ? '#FF5C00' : 'transparent',
                        boxShadow: colour === sw.hex ? '0 0 0 1px #FF5C00' : '0 0 0 1px rgba(255,255,255,0.15)',
                      }}
                    />
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
