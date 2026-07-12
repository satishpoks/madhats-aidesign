import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { ProductViewer } from './index'

const productRef = {
  name: 'Trucker',
  reference_image_url: 'front.png',
  view_images: { front: 'front.png', back: 'back.png' },
}

describe('ProductViewer', () => {
  it('shows product angles when no design yet', () => {
    render(<ProductViewer productRef={productRef} />)
    expect(screen.getByRole('img', { name: /main view/i })).toBeInTheDocument()
  })

  it('uses the composited tint for the front hero when there is no design yet', () => {
    render(
      <ProductViewer
        productRef={productRef}
        compositeViews={{ front: 'tint-front.png', back: 'tint-back.png' }}
      />,
    )
    const main = screen.getByRole('img', { name: /main view/i }) as HTMLImageElement
    expect(main.src).toContain('tint-front.png')
  })

  it('keeps the design as the front hero once a design exists (composite still used for other angles)', () => {
    render(
      <ProductViewer
        productRef={productRef}
        designUrls={['design1.png']}
        compositeViews={{ front: 'tint-front.png', back: 'tint-back.png' }}
      />,
    )
    // Design wins the main hero; the front ANGLE thumb falls back to the blank
    // photo (not the tint) once a design is present.
    const main = screen.getByRole('img', { name: /main view/i }) as HTMLImageElement
    expect(main.src).toContain('design1.png')
    fireEvent.click(screen.getByRole('button', { name: /show front/i }))
    expect((screen.getByRole('img', { name: /main view/i }) as HTMLImageElement).src).toContain('front.png')
  })

  it('promotes the newest design to the main image and swaps on thumbnail click', () => {
    render(<ProductViewer productRef={productRef} designUrls={['design1.png', 'design2.png']} />)
    const main = screen.getByRole('img', { name: /main view/i }) as HTMLImageElement
    expect(main.src).toContain('design2.png') // newest design is main
    fireEvent.click(screen.getByRole('button', { name: /show front/i }))
    expect((screen.getByRole('img', { name: /main view/i }) as HTMLImageElement).src).toContain('front.png')
  })
})
