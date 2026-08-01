import { useBrandStore } from '../store/brandStore'

/**
 * Branded studio header: store logo (or name) on the left, an optional centred
 * title, and up to 5 external main-menu links on the right. Colours come from
 * CSS vars (with MadHats fallbacks) set by brandStore.applyBrandVars.
 *
 * The title is centred by giving BOTH flanks `flex-1 basis-0`: they then share
 * the leftover space equally whatever their content width, so the middle
 * element lands dead centre. An absolutely-positioned title would centre too,
 * but would overlap the logo or the menu on a narrow screen.
 */
export function StoreHeader({ title }: { title?: string }) {
  const { brand, storeName } = useBrandStore()
  const menu = (brand.menu_items ?? []).slice(0, 5)
  const headerStyle = {
    background: 'var(--brand-header-bg, #ffffff)',
    color: 'var(--brand-header-text, #1A1D29)',
  }

  return (
    <header
      className="border-b border-border px-6 py-2 flex items-center gap-3 flex-shrink-0"
      style={headerStyle}
    >
      <div data-header-flank className="flex-1 basis-0 min-w-0 flex items-center">
        {brand.logo_url ? (
          <img src={brand.logo_url} alt={storeName || 'MAD HATS'} className="h-8 w-auto object-contain" />
        ) : (
          <span className="font-extrabold text-lg tracking-wide">
            {storeName || 'MAD HATS'}
          </span>
        )}
      </div>

      {title && (
        <span
          data-testid="header-title"
          className="flex-shrink-0 max-w-[40%] truncate text-sm font-semibold"
        >
          {title}
        </span>
      )}

      <div data-header-flank className="flex-1 basis-0 min-w-0 flex items-center justify-end">
        {menu.length > 0 && (
          <nav className="flex items-center gap-4 overflow-x-auto">
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
      </div>
    </header>
  )
}
