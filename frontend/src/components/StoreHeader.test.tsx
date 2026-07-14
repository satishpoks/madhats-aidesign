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
