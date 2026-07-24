import { useBrandStore } from '../store/brandStore'

/**
 * Branded studio header: store logo (or name), optional subtitle, and up to 5
 * external main-menu links. Colours come from CSS vars (with MadHats fallbacks)
 * set by brandStore.applyBrandVars.
 */
export function StoreHeader({ subtitle }: { subtitle?: string }) {
  const { brand, storeName } = useBrandStore()
  const menu = (brand.menu_items ?? []).slice(0, 5)
  const headerStyle = {
    background: 'var(--brand-header-bg, #ffffff)',
    color: 'var(--brand-header-text, #1A1D29)',
  }

  return (
    <header
      className="border-b border-border px-6 py-3.5 flex items-center gap-3 flex-shrink-0"
      style={headerStyle}
    >
      {brand.logo_url ? (
        <img src={brand.logo_url} alt={storeName || 'MAD HATS'} className="h-16 w-auto object-contain" />
      ) : (
        <span className="font-extrabold text-lg tracking-wide">
          {storeName || 'MAD HATS'}
        </span>
      )}
      {subtitle && <span className="text-sm truncate">{subtitle}</span>}
      {menu.length > 0 && (
        <nav className="ml-auto flex items-center gap-4 overflow-x-auto">
          {menu.map((m, i) => (
            <a
              key={i}
              href={m.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm font-medium hover:opacity-70 whitespace-nowrap"
            >
              {m.label}
            </a>
          ))}
        </nav>
      )}
    </header>
  )
}
