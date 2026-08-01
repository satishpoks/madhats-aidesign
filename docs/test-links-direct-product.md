# Test links — Shopify "Design This Hat" button (widget-shaped URLs)

Ten links built **exactly** the way `docs/shopify/studio-button.liquid:53` builds
them, from real Shopify product data — numeric `{{ product.id }}`, the first
available `{{ variant.id }}`, the variant's colour option, `source=shopify`:

```
{{ STUDIO_URL }}/?product_id={{ product.id }}&variant_id={{ current.id }}&colour={{ current_colour | url_encode }}&source=shopify
```

No internal database UUIDs anywhere. **`product_id` here is the Shopify product
id**, which is what the liquid button can actually emit.

- **Environment:** staging — `https://mhstaging.getaiconsult.com.au`
  (for prod, swap the host; the liquid's `STUDIO_URL` is set at line 30)
- **Store:** `mh_pk_madhats_local` (baked into the staging bundle; the button
  carries no store key — one Studio build per store)
- **Verified 2026-08-01:** every one of the ten Shopify ids returns `200` from
  `GET /products/{id}` **and** resolves to the matching product (checked by
  comparing the returned `store_url` handle against the Shopify handle). Link #1
  was additionally opened in a real browser — the studio booted straight into
  the canvas with the correct cap and all four faces.

## Does this work? Yes — here's the mechanism

`backend/app/services/products.py:56-76` resolves the id by shape:

```python
column = "shopify_product_id" if product_id.isdigit() else "id"
```

A **purely numeric** id is looked up against `product_references.shopify_product_id`
(populated at sync from the Shopify feed — `catalogue_sync.py:234`); anything else
is treated as the internal UUID. So the widget's `{{ product.id }}` resolves
natively, no mapping table and no theme-side lookup.

**This is also why you should never hard-code an internal UUID in the button:**
the internal `id` is a `gen_random_uuid()` and catalogue sync is delete+insert, so
it changes on every re-sync. `shopify_product_id` is the stable one.

## The 10 links

| # | Hat | Angles | Shopify product_id | Link |
|---|---|---|---|---|
| 1 | A Frame Flex Structured Snapback Cap in Cotton Twill | **4** (front/back/left/right) | 8958301896840 | https://mhstaging.getaiconsult.com.au/?product_id=8958301896840&variant_id=46142071668872&colour=Khakhi%20Maroon&source=shopify |
| 2 | 1101 Trim Snapback Cap with Flat Peak and Wool Blend | 2 (front/back) | 7271814135944 | https://mhstaging.getaiconsult.com.au/?product_id=7271814135944&variant_id=41044991672456&colour=ARMY&source=shopify |
| 3 | 5 Panel Structured Poly/Cotton Front Mesh Back Camo Trucker | 2 (front/back) | 8923338670216 | https://mhstaging.getaiconsult.com.au/?product_id=8923338670216&variant_id=45918580244616&colour=Khaki&source=shopify |
| 4 | Richardson Mesh Back Cap with Breathable Design | 2 (front/back) | 6676871381128 | https://mhstaging.getaiconsult.com.au/?product_id=6676871381128&variant_id=39652625875080&colour=Solid%20Navy&source=shopify |
| 5 | Kaleidoscope Beanie | 2 (front/back) | 7386589560968 | https://mhstaging.getaiconsult.com.au/?product_id=7386589560968&variant_id=41145797542024&colour=Pink&source=shopify |
| 6 | Heavy Brushed Cotton Peak & Back Trim Baseball Cap | 2 (front/back) | 6635024613512 | https://mhstaging.getaiconsult.com.au/?product_id=6635024613512&variant_id=39550499848328&colour=Black&source=shopify |
| 7 | 100% Coolde Structured 6-Panel Cap with Pre-Curved Peak | 1 (front only) | 6634411425928 | https://mhstaging.getaiconsult.com.au/?product_id=6634411425928&variant_id=39548351381640&colour=Black&source=shopify |
| 8 | 1117 Bucket Hat | 1 (front only) | 7271807942792 | https://mhstaging.getaiconsult.com.au/?product_id=7271807942792&variant_id=41044983971976&colour=ARMY&source=shopify |
| 9 | 5-Panel Natural Crown Visor with Coloured Curved Brim | 1 (front only) | 8882875564168 | https://mhstaging.getaiconsult.com.au/?product_id=8882875564168&variant_id=45025756971144&colour=Red&source=shopify |
| 10 | A Frame Dad Hat Unstructured | 1 (front only) | 8516036919432 | https://mhstaging.getaiconsult.com.au/?product_id=8516036919432&variant_id=43376023994504&colour=Red&source=shopify |

Styles covered: snapback, trucker, cap, beanie, baseball cap, bucket hat, visor,
dad hat.

### What to expect per link

- **#1 is the only product in the entire 1302-product catalogue with all four
  angles** — use it for multi-face render testing.
- **#7–10 are front-only.** A decoration placed on a back or side face **will not
  render**: the render loop skips faces with no genuine photo (`_map_views` no
  longer fabricates aliases). Expected behaviour. Only ~5% of the catalogue has
  any second angle at all.
- `variant_id` and `colour` do **not** change which product loads. They are stored
  as `entryContext` (`sessionStore.ts:228-235`) for attribution only. The cap
  photo shown is the product's reference image.

## Minimal form

`product_id` is the only required param. These work too:

```
https://mhstaging.getaiconsult.com.au/?product_id=8958301896840
https://mhstaging.getaiconsult.com.au/?product_id=7386589560968
```

## Failure modes worth knowing

| You pass | Result |
|---|---|
| Valid Shopify numeric id | `200` → studio opens on that hat |
| Numeric id not in the synced catalogue | `404` → studio falls back to the dev product picker (warns in console) |
| The **handle** (e.g. `kaleidoscope-beanie`) | **`500`**, not `404` |
| Internal UUID | works, but breaks at the next catalogue sync — don't use |

The handle case is a genuine rough edge: a non-numeric id goes to the `id` column,
and Postgres raises a uuid type error rather than returning empty. Harmless for
the liquid button (it only ever emits `{{ product.id }}`), but a hand-typed or
mis-templated link gives a 500 instead of a clean not-found. Worth a ticket if you
want it tidy.

If a link drops to the product picker instead of opening the hat, the usual cause
is **the product isn't in that store's synced catalogue** — not a bad URL. Check
`GET /products/{id}` directly (below) before debugging the button.

## Verify any product id yourself

```bash
curl -s -H "X-Store-Key: mh_pk_madhats_local" \
  "https://api.mhstaging.getaiconsult.com.au/products/8958301896840" | head -c 300
```

`200` means the widget URL for that product will work. Get ids straight from
Shopify with `https://madhats.com.au/products.json?limit=250&page=1` (`id` +
`handle` per product) — note that feed is fetchable from a normal/residential
connection but is refused from the backend container, which is why catalogue
sync runs in the `catalogue-sync` sidecar.
