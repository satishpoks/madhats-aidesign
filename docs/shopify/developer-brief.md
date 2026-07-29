# Brief — "Design This Hat with AI" button

For the MadHats in-house Shopify developer. Everything referenced here is in
this folder: `studio-button.liquid` (the snippet) and `README.md` (fuller
install notes).

## What it's for

MadHats has a new **AI Design Studio** — a separate web app where a customer
designs a cap on an interactive canvas (place a logo, add text, pick a
decoration method), sees an AI-rendered photoreal mockup of that exact cap, and
requests a quote. The button is the **entry point from the product page**: it
hands the Studio the product the customer is already looking at, so they don't
re-pick it.

**This does not replace InkyBay.** InkyBay stays exactly as it is. The Studio
button is an additional call-to-action alongside it.

## What to do

1. Set `STUDIO_URL` at the top of `studio-button.liquid` to the host we give you
   (`https://`, no port, no trailing slash — staging first, prod at go-live).
2. Install it as either a snippet (`snippets/madhats-studio-button.liquid` +
   `{% render 'madhats-studio-button' %}`) or a **Custom Liquid** block in the
   theme editor. Your call — whichever fits the theme.
3. Place it on the product page under (or beside) Add to Cart. Restyle the
   `.madhats-studio-button` CSS to match the theme; the markup and the link are
   the parts that must stay intact.
4. Decide with us which products get it. It can be every cap, or gated on a tag
   / product type if we only want it on a subset.

Please don't push to the live theme without a heads-up — we'll confirm the
store's catalogue is synced first (see "If it doesn't work" below).

## How it should behave

- **Opens in a new tab** (`target="_blank" rel="noopener"`). The customer keeps
  their place on the storefront.
- **Carries the product**: the link's `product_id` is `{{ product.id }}` — the
  numeric Shopify product id. Never substitute a hard-coded or internal id; the
  Studio resolves products by the Shopify id specifically.
- **Follows the variant selector.** The snippet's inline script rewrites
  `variant_id` and `colour` in the link as the customer changes variant. If your
  theme's selector is unusual and the script can't hook it, it fails silent and
  the link keeps its server-rendered value (first available variant) — that's
  acceptable, not a bug to chase.
- **Never interferes with Add to Cart.** It's an `<a>`, not a `<button>`, so it
  is safe inside the product form — please keep it that way.
- **Carries no keys or customer data.** Just the product/variant/colour ids and
  `source=shopify`. Nothing to configure per-product.
- Works on mobile at the same place in the layout.

## What success looks like

Click the button on a product page and you should land, in a new tab, **directly
in the design canvas with that exact cap already loaded** — its real product
photo, its colour, and the four face tabs (front / back / left / right) ready to
design on. No product picker, no "choose a hat" step, no login.

Then check two more things:

- Change the variant on the product page **before** clicking — the Studio should
  open on the matching colourway.
- Try it on two different products — each should open its own cap.

**If instead you land on a "pick a product" screen**, the link reached the
Studio but the product wasn't recognised. Open the browser console; you'll see
`[MadHats] bootstrapFromUrl failed`. **That is our side, not the theme** — it
means either the product isn't in the Studio's synced catalogue yet or the
Studio build is pointed at the wrong store. Send us the product URL and we'll
fix it; nothing in the snippet needs changing.

## Questions to send back to us

- Which products should show the button (all caps, or a tag/type subset)?
- Where in the product page do you want it, and do you want us to match a
  specific theme button style?
- Anything in the theme that would conflict with a new tab opening (a quick-view
  modal, a sticky ATC bar that re-renders the block, etc.)?
