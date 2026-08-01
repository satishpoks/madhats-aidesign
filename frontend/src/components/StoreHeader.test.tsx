import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StoreHeader } from './StoreHeader'
import { useBrandStore } from '../store/brandStore'

describe('StoreHeader', () => {
  beforeEach(() => {
    useBrandStore.setState({ brand: {}, storeName: '', personaName: '', loaded: true })
  })

  it('renders the store name when no logo', () => {
    useBrandStore.setState({ storeName: 'Acme Caps', brand: {} })
    render(<StoreHeader />)
    expect(screen.getByText('Acme Caps')).toBeInTheDocument()
  })

  it('renders a logo img when logo_url set', () => {
    useBrandStore.setState({ storeName: 'Acme', brand: { logo_url: 'http://x/logo.png' } })
    render(<StoreHeader />)
    expect(screen.getByRole('img', { name: /acme/i })).toHaveAttribute('src', 'http://x/logo.png')
  })

  it('renders menu links with target=_blank + rel', () => {
    useBrandStore.setState({ storeName: 'Acme', brand: { menu_items: [{ label: 'Shop', url: 'https://acme.example/shop' }] } })
    render(<StoreHeader />)
    const link = screen.getByRole('link', { name: 'Shop' })
    expect(link).toHaveAttribute('href', 'https://acme.example/shop')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('falls back to MAD HATS when nothing set', () => {
    render(<StoreHeader />)
    expect(screen.getByText('MAD HATS')).toBeInTheDocument()
  })
})

describe('centred title', () => {
  it('renders the title with no breadcrumb suffix', () => {
    render(<StoreHeader title="Classic Snapback" />)
    expect(screen.getByTestId('header-title').textContent).toBe('Classic Snapback')
  })

  it('centres it with equal-basis flanks, not absolute positioning', () => {
    // `flex-1 basis-0` on BOTH flanks makes them share the leftover space
    // equally whatever their content, which centres the middle exactly. An
    // absolutely-positioned title would overlap the logo or the menu on a
    // narrow screen instead.
    render(<StoreHeader title="Classic Snapback" />)
    const title = screen.getByTestId('header-title')
    const header = title.closest('header')!
    const flanks = header.querySelectorAll('[data-header-flank]')
    expect(flanks).toHaveLength(2)
    flanks.forEach(f => {
      expect(f.className).toContain('flex-1')
      expect(f.className).toContain('basis-0')
    })
    expect(title.className).not.toContain('absolute')
  })

  it('renders no title node when none is given', () => {
    render(<StoreHeader />)
    expect(screen.queryByTestId('header-title')).toBeNull()
  })
})
