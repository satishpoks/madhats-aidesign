# Shopify "Design This Hat" button → MadHats AI Design Studio

A drop-in button for the Shopify product page. Clicking it opens the AI Design
Studio for **the product the customer is viewing**, in a new tab.

## What the link looks like

```
{STUDIO_URL}/?product_id={{ product.id }}&variant_id=…&colour=…&source=shopify
```

| Param | Value | Required |
|---|---|---|
| `product_id` | `{{ product.id }}` — the Shopify numeric product id | **yes** |
| `variant_id` | currently selected variant (kept in sync on variant change) | no |
| `colour` | the product's colour-option value, if it has one | no |
| `source` | `shopify` (attribution — lands in the session's `entryContext`) | no |

> **Why `{{ product.id }}` works:** the Studio backend resolves a numeric
> `product_id` against `product_references.shopify_product_id` (stable across
> catalogue syncs). It does **not** use the internal DB UUID, which is
> regenerated every time the catalogue re-syncs. So always pass `{{ product.id }}`
> — never a hard-coded internal id.

## Prerequisites

1. **The store is onboarded and its catalogue is synced** so the product exists
   in `product_references` for this store:
   `POST /admin/stores` → `POST /admin/stores/{id}/sync`.
2. **The Studio deployment is built for this store** — its `VITE_STORE_KEY` is
   the store's publishable key. The button carries no store key; the frontend
   already knows which store it is. (One Studio deployment per store.)
3. You know the **Studio host URL** (e.g. `http://madhats.getaiconsult.com.au:5173`).

## Install (recommended — Liquid snippet)

1. In the Shopify admin: **Online Store → Themes → … → Edit code**.
2. Open `studio-button.liquid` (in this folder), set `STUDIO_URL` at the top to
   your Studio host (no trailing slash).
3. Add it to the theme in **one** of these ways:
   - **Snippet:** create `snippets/madhats-studio-button.liquid`, paste the
     contents, then render it in your product template
     (`sections/main-product.liquid` or `templates/product.liquid`):
     ```liquid
     {% render 'madhats-studio-button' %}
     ```
   - **Custom Liquid block (no code edit):** in the theme editor, on the product
     page, **Add block → Custom Liquid**, and paste the snippet contents.
     Position it wherever you want (e.g. under the Add-to-Cart button).

The button styles are self-contained, so it looks consistent regardless of
theme. Restyle via the `.madhats-studio-button` CSS at the bottom of the snippet.

## Plain-HTML fallback (no Liquid available)

If you're pasting into a context without Liquid variables (a landing page, an
email, a hard-coded link for a single product), use a static link. You must fill
in the product's numeric Shopify id yourself:

```html
<a href="http://madhats.getaiconsult.com.au:5173/?product_id=8123456789&source=shopify"
   target="_blank" rel="noopener"
   style="display:inline-flex;align-items:center;gap:8px;padding:12px 20px;
          border-radius:8px;background:#111827;color:#fff;font-weight:600;
          font-size:15px;text-decoration:none;">
  ✨ Design This Hat with AI
</a>
```

Find a product's numeric id in the Shopify admin URL
(`…/products/8123456789`) or via `{{ product.id }}` in a theme.

## Testing it

1. Click the button on a product page → a new tab opens the Studio.
2. It should land directly on the **canvas Design Studio** for that cap (not the
   dev product picker). If it drops to the picker, the browser console logs
   `[MadHats] bootstrapFromUrl failed` — the usual cause is the product not being
   in this store's catalogue (re-run the store sync) or the Studio being built
   with the wrong `VITE_STORE_KEY`.

## How the frontend consumes it

`frontend/src/store/sessionStore.ts` → `bootstrapFromUrl()` reads the query
params on load and routes:

- `?session=<token>` → resume an existing session (preview-email "make edits" link)
- `?mode=blank` → blank-hat picker
- **`?product_id=<id>`** → fetch the product and open its canvas session ← this button
- (none) → dev product picker
