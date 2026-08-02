import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { BrandingView } from './BrandingView'
import * as api from '../adminApi'

vi.mock('../adminApi', async (orig) => {
  const actual = await orig<typeof api>()
  return {
    ...actual,
    listStores: vi.fn(async () => [{ id: 's1', slug: 'acme', name: 'Acme', public_key: 'k', shopify_domain: null, status: 'active' }]),
    getStore: vi.fn(async () => ({ id: 's1', slug: 'acme', name: 'Acme', brand: { primary_colour: '#123456', menu_items: [] } })),
    updateStoreBrand: vi.fn(async (_id: string, brand) => ({ id: 's1', slug: 'acme', name: 'Acme', brand })),
    uploadStoreLogo: vi.fn(async () => ({ logo_url: 'http://x/logo.png' })),
  }
})

function renderView() {
  return render(<MemoryRouter initialEntries={['/admin/branding?store=s1']}><BrandingView /></MemoryRouter>)
}

describe('BrandingView', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads and shows the store primary colour', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalledWith('s1'))
    expect(await screen.findByRole('textbox', { name: 'primary_colour' })).toHaveValue('#123456')
  })

  it('blocks a 6th menu item', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    // add 5 rows -> the "Add menu item" control disables at 5
    for (let i = 0; i < 5; i++) fireEvent.click(screen.getByRole('button', { name: /add menu item/i }))
    expect(screen.getByRole('button', { name: /add menu item/i })).toBeDisabled()
  })

  it('rejects a non-http url on save', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /add menu item/i }))
    fireEvent.change(screen.getByPlaceholderText(/label/i), { target: { value: 'Bad' } })
    // The colour reference links share the same "https://…" placeholder, so
    // disambiguate: the menu row's url input is the last https-placeholder
    // field in document order.
    const urlInputs = screen.getAllByPlaceholderText(/https/i)
    fireEvent.change(urlInputs[urlInputs.length - 1], { target: { value: 'javascript:alert(1)' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    // This is the MENU-LINK error, not the redirect-url one — tightened from a
    // bare /http\(s\)/i (which also matches "Redirect URL must be an http(s)
    // URL" and "Colour reference links must be full http(s) URLs") to the
    // menu-link message specifically, so this test can't silently pass on the
    // wrong one of the three surfacing instead.
    expect(await screen.findByText(/menu links must be/i)).toBeInTheDocument()
    expect(api.updateStoreBrand).not.toHaveBeenCalled()
  })

  // --- Workstream D: the "Flow steps" card ------------------------------------

  it('never surfaces a dependency-locked step', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    expect(await screen.findByText('Flow steps')).toBeInTheDocument()
    // Only the safe subset is offered; email/decoration/finalize are locked.
    // Three since workstream B's `needed_by` joined the configurable subset.
    expect(screen.getAllByRole('checkbox')).toHaveLength(3)
    // The locked `ask_email` step must not appear as a flow-step checkbox.
    // (Scoped to a checkbox so it doesn't match the unrelated "Sales
    // notification email" input field, which legitimately carries "email".)
    expect(screen.queryByRole('checkbox', { name: /email/i })).not.toBeInTheDocument()
  })

  it('persists a reorder into brand.canvas_flow', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.click(await screen.findByRole('button', { name: /move what is the hat for\? up/i }))
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(api.updateStoreBrand).toHaveBeenCalled())
    const brand = vi.mocked(api.updateStoreBrand).mock.calls[0][1]
    // Default order is quantity -> needed_by -> purpose (workstream B inserted
    // needed_by between them), so one "up" click on purpose swaps it with
    // needed_by rather than putting it first. Still a genuine reorder off the
    // default, which is what this test asserts is persisted.
    expect(brand.canvas_flow?.steps).toEqual([
      { id: 'ask_quantity', enabled: true },
      { id: 'ask_purpose', enabled: true },
      { id: 'needed_by', enabled: true },
    ])
  })

  it('persists a disabled step', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.click(await screen.findByRole('checkbox', { name: /what is the hat for\? enabled/i }))
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(api.updateStoreBrand).toHaveBeenCalled())
    const brand = vi.mocked(api.updateStoreBrand).mock.calls[0][1]
    expect(brand.canvas_flow?.steps).toContainEqual({ id: 'ask_purpose', enabled: false })
  })

  // --- Colour reference guide links (pre-quote colour disclaimer) ------------

  it('renders and edits the colour reference link fields', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    const embroidery = await screen.findByLabelText('Embroidery colour chart URL')
    const print = screen.getByLabelText('Print colour guide URL')
    fireEvent.change(embroidery, { target: { value: 'https://acme.test/e' } })
    fireEvent.change(print, { target: { value: 'https://acme.test/p' } })
    expect((embroidery as HTMLInputElement).value).toBe('https://acme.test/e')
    expect((print as HTMLInputElement).value).toBe('https://acme.test/p')
  })

  it('rejects a non-http colour reference link on save', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.change(await screen.findByLabelText('Embroidery colour chart URL'),
      { target: { value: 'ftp://acme.test/e' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    expect(await screen.findByText(/http\(s\) URLs/i)).toBeInTheDocument()
    expect(api.updateStoreBrand).not.toHaveBeenCalled()
  })

  // --- Sales notification email ----------------------------------------------

  it('loads the current sales notification email and saves an edit', async () => {
    vi.mocked(api.getStore).mockResolvedValueOnce({
      id: 's1', slug: 'acme', name: 'Acme',
      brand: { primary_colour: '#123456', menu_items: [] },
      sales_notification_email: 'old@acme.example',
    })
    renderView()
    const input = await screen.findByLabelText('Sales notification email')
    expect(input).toHaveValue('old@acme.example')
    fireEvent.change(input, { target: { value: 'new@acme.example' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(api.updateStoreBrand).toHaveBeenCalled())
    // 3rd positional arg carries the sales email alongside the brand PATCH.
    expect(vi.mocked(api.updateStoreBrand).mock.calls[0][2]).toBe('new@acme.example')
  })

  it('rejects an invalid sales notification email on save', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.change(await screen.findByLabelText('Sales notification email'),
      { target: { value: 'not-an-email' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    expect(await screen.findByText(/valid.*email/i)).toBeInTheDocument()
    expect(api.updateStoreBrand).not.toHaveBeenCalled()
  })

  // --- Canvas accent + chat bubble colours ------------------------------------

  it('renders pickers for canvas accent and chat bubble, and saves them', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    const canvasAccent = await screen.findByRole('textbox', { name: 'canvas_accent' })
    const chatBubble = screen.getByRole('textbox', { name: 'chat_user_bubble' })
    fireEvent.change(canvasAccent, { target: { value: '#00AA55' } })
    fireEvent.change(chatBubble, { target: { value: '#AA0055' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(api.updateStoreBrand).toHaveBeenCalled())
    const brand = vi.mocked(api.updateStoreBrand).mock.calls[0][1]
    expect(brand.canvas_accent).toBe('#00AA55')
    expect(brand.chat_user_bubble).toBe('#AA0055')
  })

  it('rejects a malformed canvas_accent on save', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.change(await screen.findByRole('textbox', { name: 'canvas_accent' }),
      { target: { value: 'not-a-hex' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    expect(await screen.findByText(/canvas_accent.*hex colour/i)).toBeInTheDocument()
    expect(api.updateStoreBrand).not.toHaveBeenCalled()
  })

  it('rejects a malformed chat_user_bubble on save', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.change(await screen.findByRole('textbox', { name: 'chat_user_bubble' }),
      { target: { value: 'not-a-hex' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    expect(await screen.findByText(/chat_user_bubble.*hex colour/i)).toBeInTheDocument()
    expect(api.updateStoreBrand).not.toHaveBeenCalled()
  })

  it('shows the canvas accent and chat bubble colours in the live preview', async () => {
    vi.mocked(api.getStore).mockResolvedValueOnce({
      id: 's1', slug: 'acme', name: 'Acme',
      brand: { primary_colour: '#123456', canvas_accent: '#00AA55', chat_user_bubble: '#AA0055', menu_items: [] },
    })
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    expect(await screen.findByText('Canvas tool')).toHaveStyle({ background: '#00AA55' })
    expect(screen.getByText("Customer's chat bubble")).toHaveStyle({ background: '#AA0055' })
  })

  // --- Return to shop (redirect after quote) ----------------------------------

  it('rejects a non-http redirect url before saving', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.change(await screen.findByLabelText(/redirect url/i), { target: { value: 'madhats.com.au' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    // Tightened from a bare /http\(s\)/i, which also matches the menu-link and
    // colour-reference error strings ("Menu links must be full http(s) URLs",
    // "Colour reference links must be full http(s) URLs") — that regex would
    // pass this test even if `validate()` surfaced the WRONG one of the three.
    expect(await screen.findByText(/redirect url must be/i)).toBeInTheDocument()
    expect(api.updateStoreBrand).not.toHaveBeenCalled()
  })

  it('rejects a countdown outside 5-300 seconds', async () => {
    vi.mocked(api.getStore).mockResolvedValueOnce({
      id: 's1', slug: 'acme', name: 'Acme',
      brand: { primary_colour: '#123456', menu_items: [], redirect_url: 'https://madhats.com.au', redirect_seconds: 30 },
    })
    renderView()
    const secs = await screen.findByLabelText(/countdown/i)
    fireEvent.change(secs, { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    expect(await screen.findByText(/between 5 and 300/i)).toBeInTheDocument()
    expect(api.updateStoreBrand).not.toHaveBeenCalled()
  })

  it('rejects an out-of-range countdown even when no redirect url is set', async () => {
    // Mirrors the server: `_validate_redirect` checks redirect_seconds
    // whenever the key is present in the payload at all, independent of
    // redirect_url. Editing the Countdown field is what puts the key in
    // `brand` state, so this reproduces the real admin sequence: type a
    // countdown, leave the URL blank, save — and the server would 400.
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    const secs = await screen.findByLabelText(/countdown/i)
    fireEvent.change(secs, { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    expect(await screen.findByText(/between 5 and 300/i)).toBeInTheDocument()
    expect(api.updateStoreBrand).not.toHaveBeenCalled()
  })

  it('does not block saving unrelated changes on a store with no redirect configured', async () => {
    // An untouched store's `brand` never carries a `redirect_seconds` key —
    // GET /admin/stores/{id} returns the raw stored brand with nothing
    // injected, and the Countdown input's `?? 30` is a display fallback
    // only, never written into state. Leaving the field untouched must not
    // block saving an unrelated change.
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.change(await screen.findByRole('textbox', { name: 'primary_colour' }), { target: { value: '#654321' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(api.updateStoreBrand).toHaveBeenCalled())
    const brand = vi.mocked(api.updateStoreBrand).mock.calls[0][1]
    expect(brand.primary_colour).toBe('#654321')
    expect('redirect_seconds' in brand).toBe(false)
  })

  it('rejects a redirect url with no real host (empty netloc)', async () => {
    // Server-fidelity case: urlparse('https://?a=b').netloc is '', so
    // branding.py rejects it. The client regex must too, not just the
    // scheme prefix.
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.change(await screen.findByLabelText(/redirect url/i), { target: { value: 'https://?a=b' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    // Tightened from a bare /http\(s\)/i, which also matches the menu-link and
    // colour-reference error strings ("Menu links must be full http(s) URLs",
    // "Colour reference links must be full http(s) URLs") — that regex would
    // pass this test even if `validate()` surfaced the WRONG one of the three.
    expect(await screen.findByText(/redirect url must be/i)).toBeInTheDocument()
    expect(api.updateStoreBrand).not.toHaveBeenCalled()
  })

  it('allows a blank redirect url as the off switch and saves it', async () => {
    vi.mocked(api.getStore).mockResolvedValueOnce({
      id: 's1', slug: 'acme', name: 'Acme',
      brand: { primary_colour: '#123456', menu_items: [], redirect_url: 'https://madhats.com.au', redirect_seconds: 30 },
    })
    renderView()
    const urlField = await screen.findByLabelText(/redirect url/i)
    expect(urlField).toHaveValue('https://madhats.com.au')
    fireEvent.change(urlField, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(api.updateStoreBrand).toHaveBeenCalled())
    const brand = vi.mocked(api.updateStoreBrand).mock.calls[0][1]
    expect(brand.redirect_url).toBe('')
  })
})
