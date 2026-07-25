import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { linkify } from './linkify'

describe('linkify', () => {
  it('turns a URL into a new-tab anchor and keeps surrounding text', () => {
    render(<p>{linkify('See https://acme.test/chart for colours.')}</p>)
    const a = screen.getByRole('link')
    expect(a).toHaveAttribute('href', 'https://acme.test/chart')
    expect(a).toHaveAttribute('target', '_blank')
    expect(a).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByText(/for colours\./)).toBeInTheDocument()
  })

  it('does not include trailing punctuation in the href', () => {
    render(<p>{linkify('go to https://acme.test/x.')}</p>)
    expect(screen.getByRole('link')).toHaveAttribute('href', 'https://acme.test/x')
  })

  it('leaves plain text without links untouched', () => {
    render(<p>{linkify('no links here')}</p>)
    expect(screen.queryByRole('link')).toBeNull()
  })
})
