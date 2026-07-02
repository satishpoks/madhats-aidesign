import { useState, useEffect } from 'react'
import { fetchProducts } from '../../lib/api'
import type { Product } from '../../lib/types'
import { useSessionStore } from '../../store/sessionStore'

const LIMIT = 24

function ProductSkeleton() {
  return (
    <div className="bg-surface border border-border rounded-2xl p-4">
      <div className="aspect-square w-full mb-3 rounded-xl shimmer" />
      <div className="space-y-2">
        <div className="h-3 w-3/4 rounded shimmer" />
        <div className="h-3 w-1/2 rounded shimmer" />
      </div>
    </div>
  )
}

export function ApiProductPicker() {
  const startSession = useSessionStore(s => s.startSession)

  const [products, setProducts] = useState<Product[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    fetchProducts(LIMIT, 0)
      .then(page => {
        setProducts(page.items)
        setTotal(page.total)
        setOffset(LIMIT)
        setLoading(false)
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load products')
        setLoading(false)
      })
  }, [])

  async function handleLoadMore() {
    setLoadingMore(true)
    try {
      const page = await fetchProducts(LIMIT, offset)
      setProducts(prev => [...prev, ...page.items])
      setTotal(page.total)
      setOffset(prev => prev + LIMIT)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load more products')
    } finally {
      setLoadingMore(false)
    }
  }

  const [selectError, setSelectError] = useState<string | null>(null)

  async function handleSelect(product: Product) {
    setSelectError(null)
    try {
      await startSession(product)
    } catch (err) {
      setSelectError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
    }
  }

  return (
    <div className="min-h-screen bg-base flex flex-col">
      {/* Header */}
      <header className="bg-ink px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-accent font-bold text-xl tracking-tight">MadHats</span>
          <span className="text-white/30 text-xl">|</span>
          <span className="text-white/80 text-sm font-medium">AI Design Studio</span>
        </div>
        <span className="text-xs text-white/70 border border-white/20 px-3 py-1 rounded-full">
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
      </div>

      {/* Session-creation error banner */}
      {selectError && (
        <div
          role="alert"
          className="mx-6 mb-2 flex items-start justify-between gap-3 rounded-xl border border-accent bg-surface px-4 py-3"
        >
          <p className="text-sm text-textPrimary">{selectError}</p>
          <button
            onClick={() => setSelectError(null)}
            aria-label="Dismiss error"
            className="flex-shrink-0 text-xs text-textMuted hover:text-accent transition-colors"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Product grid */}
      <div className="px-6 pb-12 flex-1">
        <p className="text-xs text-textMuted uppercase tracking-widest mb-4 font-medium">
          Choose a style
        </p>

        {loading && (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <ProductSkeleton key={i} />
            ))}
          </div>
        )}

        {error && !loading && (
          <div className="flex flex-col items-center justify-center py-16 gap-4">
            <p className="text-textMuted text-sm">{error}</p>
            <button
              onClick={() => {
                setError(null)
                setLoading(true)
                fetchProducts(LIMIT, 0)
                  .then(page => {
                    setProducts(page.items)
                    setTotal(page.total)
                    setOffset(LIMIT)
                  })
                  .catch((err: unknown) => {
                    setError(err instanceof Error ? err.message : 'Failed to load products')
                  })
                  .finally(() => setLoading(false))
              }}
              className="px-4 py-2 text-sm border border-border rounded-full text-textMuted hover:border-accent hover:text-accent transition-all"
            >
              Try again
            </button>
          </div>
        )}

        {!loading && !error && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {products.map(product => (
                <button
                  key={product.id}
                  onClick={() => void handleSelect(product)}
                  className="bg-surface border border-border rounded-2xl p-4 text-left cursor-pointer group hover:border-accent transition-all duration-200 shadow-sm hover:shadow-[0_0_0_1px_#FF5C00] animate-fadeIn"
                >
                  {/* Product image */}
                  <div className="aspect-square w-full mb-3 overflow-hidden rounded-xl bg-surfaceAlt">
                    <img
                      src={product.reference_image_url}
                      alt={product.name}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      loading="lazy"
                    />
                  </div>

                  {/* Info */}
                  <div className="space-y-1">
                    <p className="text-textPrimary text-sm font-semibold leading-tight">{product.name}</p>
                    <p className="text-textMuted text-xs">{product.colour}</p>
                    {product.description && (
                      <p className="text-textMuted text-xs line-clamp-2 mt-1">{product.description}</p>
                    )}
                  </div>
                </button>
              ))}
            </div>

            {products.length < total && (
              <div className="flex justify-center mt-8">
                <button
                  onClick={() => void handleLoadMore()}
                  disabled={loadingMore}
                  className="px-6 py-2.5 bg-surface border border-border rounded-full text-sm text-textPrimary hover:border-accent hover:text-accent transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {loadingMore ? (
                    <span className="flex items-center gap-2">
                      <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
                      Loading…
                    </span>
                  ) : (
                    `Load more (${total - products.length} remaining)`
                  )}
                </button>
              </div>
            )}

            {products.length === 0 && !loading && (
              <p className="text-center text-textMuted py-16 text-sm">No products available yet.</p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
