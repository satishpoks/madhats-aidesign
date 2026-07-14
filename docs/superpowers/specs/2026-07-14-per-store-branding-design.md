# Per-Store Branding & Themed Emails — Design

**Date:** 2026-07-14
**Status:** Approved (design), pending implementation plan

---

## 1. Problem & Goal

The customer-facing Design Studio is hardcoded to MadHats branding (the header
literally renders `MAD HATS` in the fixed accent colour `#FF5C00`, and every
`text-accent`/`bg-accent` usage is that one orange). The platform is already
multi-tenant (10+ stores from one backend + DB), but every tenant's storefront
widget looks identical.

**Goal:** let each store present the Design Studio — and the emails it sends —
in that store's own branding: logo, primary colour, header colours, and a small
configurable main menu of external links. Configured by the global agency admin
today, with the API shaped so a future per-store-owner login can reuse it.

### Non-goals (explicitly out of scope)
- **No per-store-owner authentication.** Branding is edited through the existing
  global admin console (single `X-Admin-Secret`) using the store-selector
  pattern already used by Hat Types / Graphics / Decorations. A future
  store-owner login is anticipated in the API shape but not built here.
- **No sub-menus.** Main menu only, max 5 items, external URLs only.
- **No full palette re-skin.** Only logo + primary colour + header bg/text are
  themeable. Base/surface/text stay fixed to avoid low-contrast/unreadable UI.
- **Internal emails stay unbranded.** Only customer-facing emails are themed.
- **The canvas "remove background" bug is unrelated** and handled separately.

---

## 2. Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Who configures | Global admin now (existing console + store selector); API designed so a store-owner login can reuse it later |
| Theme depth | Logo + one primary/accent colour + header background + header text. Neutral base/surface/text fixed. |
| Menu items | ≤5, main menu only, no sub-menus, external `http(s)` URLs, open in a new tab |
| Email theming | Customer-facing only (preview / verification / resume). Internal sales/ops emails stay plain. |

---

## 3. Data Model

No new table. Extend the existing `stores.brand` jsonb (already
`{primary_colour, logo_url, watermark_asset_url}`). One migration documents the
widened shape (comment only; jsonb needs no structural change):

```jsonc
brand: {
  logo_url:            "storage path, served via the /media proxy",
  primary_colour:      "#FF5C00",   // → Tailwind `accent`: buttons, links, highlights
  header_bg:           "#FFFFFF",
  header_text:         "#1A1D29",
  watermark_asset_url: "…",          // unchanged, pre-existing
  menu_items: [
    { "label": "Shop",  "url": "https://store.example/shop" },
    { "label": "About", "url": "https://store.example/about" }
    // … up to 5
  ]
}
```

Rationale for one blob: `brand` is already threaded through `admin_stores.py`;
a single jsonb keeps it to one PATCH with no column churn. `menu_items` lives
under `brand` for the same reason.

All fields are optional. Missing values fall back to the current MadHats
defaults so unconfigured stores are visually unchanged.

---

## 4. Backend

### 4.1 New customer endpoint — `GET /storefront`
- Resolved via `require_store` (the `X-Store-Key` publishable key the widget
  already sends).
- Returns the **public** subset only:
  ```json
  {
    "name": "…",
    "persona_name": "…",
    "brand": {
      "logo_url": "…proxied /media URL…",
      "primary_colour": "#…",
      "header_bg": "#…",
      "header_text": "#…",
      "menu_items": [ { "label": "…", "url": "…" } ]
    }
  }
  ```
- Never returns secrets, `allowed_origins`, `sales_notification_email`, etc.
- `logo_url` is returned as a `/media` proxy URL (never a raw signed bucket URL).
- Shape is reused by a future store-owner login (same serializer).

### 4.2 Logo upload — `POST /admin/stores/{id}/logo`
- Gated by `X-Admin-Secret`.
- Reuses the existing logo/graphics upload+validation helper (size limit +
  MIME + magic-byte sniff via `sniff_image_mime`).
- Stores into the private bucket; persists the storage path into
  `brand.logo_url`; returns the `/media` proxy URL.

### 4.3 Extend `PATCH /admin/stores/{id}`
Accept the new `brand` keys + `menu_items`. **Server-side validation (source of
truth):**
- `menu_items`: at most 5; each item's `label` non-empty (trimmed, length cap)
  and `url` must parse as `http`/`https` (reject `javascript:`, `data:`, etc.).
- Colours (`primary_colour`, `header_bg`, `header_text`): valid CSS hex
  (`#rgb`/`#rrggbb`), else rejected.
- Unknown keys ignored; omitted keys left unchanged (partial update semantics).

---

## 5. Frontend — Theming

### 5.1 CSS-variable tokens
Promote the decisive Tailwind tokens to CSS variables **with fallbacks** so
existing usages need zero edits:
```js
// tailwind.config
accent:      'var(--brand-primary, #FF5C00)',
accentHover: 'var(--brand-primary-hover, #E64F00)',
```
Header colours are applied via `--brand-header-bg` / `--brand-header-text`
(consumed by the header component's inline style, since header currently uses
`bg-surface` + a fixed text colour).

Because `accent` is a token, **every** existing `text-accent` / `bg-accent` /
`border-accent` usage across the app becomes themeable automatically.

`--brand-primary-hover`: if a store sets only `primary_colour`, derive the hover
shade (slightly darkened) at theme-apply time so buttons keep a hover state.

### 5.2 `ThemeProvider`
- App-root provider. On mount, fetches `GET /storefront` once (with the
  `X-Store-Key`), sets the CSS vars on `document.documentElement`, and exposes
  `{ brand, menuItems, storeName, personaName }` via React context.
- Until the fetch resolves, the built-in fallbacks (current MadHats look) apply —
  no flash of unstyled/broken theme.
- On fetch failure, silently keep fallbacks (studio must still work).

### 5.3 Header + menu
- `CustomiseStudio` header (and the BlankHatPicker / product-picker entry
  screens) render:
  - **Logo** `<img>` when `brand.logo_url` is set; otherwise the store **name**
    text (falling back to `MAD HATS` only if name is absent).
  - Header background/text from the CSS vars.
  - The **≤5 menu items** as `<a href target="_blank" rel="noopener noreferrer">`.
    On mobile the menu collapses (simple wrap or a compact menu — kept minimal).

---

## 6. Frontend — Admin Branding editor

New **Branding** view in the admin console, following the existing store-scoped
view pattern (store selector → `public_key` context; persists across views via
the `?store=<id>` query param, matching Hat Types / Graphics).

Sections (independently saveable, matching the CMS-style editors already in the
repo):
- **Logo:** upload (with preview) → `POST /admin/stores/{id}/logo`.
- **Colours:** colour pickers for primary / header bg / header text, with a
  **live preview** panel showing a mock header + a sample primary button so the
  admin sees the result before saving.
- **Menu:** add/remove rows (max 5), each `label` + `url`, with inline
  validation (non-empty label, `http(s)` URL) mirroring the server rules.

Saves via the extended `PATCH /admin/stores/{id}`.

---

## 7. Emails (customer-facing only)

Extend the customer-facing templates — `PREVIEW_EMAIL_HTML` (in `prompts`) plus
the verification and resume emails — to accept:
- `store_name` — used in copy / header.
- `primary_colour` — CTA/button + accent colour in the template.
- `logo_url` — rendered at the top, **inlined as a CID attachment** (same
  mechanism the preview image already uses) so it renders reliably in Gmail
  rather than depending on a reachable/TTL-limited URL. Falls back to the store
  name text when no logo.

Delivery already loads the session's store (for the sales email), so the brand
is available at send time; thread it into `send_preview_email` /
`send_verification_email` / `send_resume_email`. When brand fields are absent,
the templates render exactly as today (MadHats defaults).

Internal emails (`send_quote_to_sales`, `send_quote_confirmation_to_sales`,
`send_generation_alert`) are left unbranded.

---

## 8. Testing

**Backend**
- `GET /storefront` returns only public fields; excludes secrets; logo as
  `/media` URL; correct per `X-Store-Key`.
- `PATCH` validation: rejects >5 menu items, empty labels, non-`http(s)` URLs,
  invalid hex; accepts valid partial updates; leaves omitted keys unchanged.
- Logo upload: MIME/magic-byte sniff rejects non-images; persists path; returns
  proxy URL.
- Email templates render with brand (logo CID, primary colour, store name) and
  without brand (unchanged MadHats default).

**Frontend**
- `ThemeProvider` sets CSS vars from a mocked `/storefront`; falls back cleanly
  on fetch failure.
- Header renders logo when set, store-name fallback otherwise, and the menu
  items with `target="_blank" rel="noopener noreferrer"`.
- Branding editor: menu validation (max 5, url scheme, empty label), colour
  live-preview updates, save calls PATCH with the right payload.

---

## 9. Backward compatibility

- Unconfigured stores render identically to today (all brand fields fall back to
  current MadHats values).
- No breaking DB change (jsonb widening only).
- No change to internal emails, generation, or the canvas pipeline.

---

## 10. Out of Scope — tracked separately

- **Canvas "remove background" bug:** the toggle runs real client-side WASM
  matting (`@imgly/background-removal`), not a prompt flag; "nothing happens" is
  most likely first-run model download latency or the package missing inside the
  frontend Docker container. Confirm in-browser + UX improvement (clear
  "downloading model…" state) handled as a separate task.
