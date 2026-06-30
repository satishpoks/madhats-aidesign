-- =========================================================================
-- Product catalogue seed — real MadHats (madhats.com.au) products.
-- Sourced from the live Shopify products.json feed.
--
-- Image-view notes:
--   * "A Frame Flex Cap" ships true studio angle shots
--     (Front / Back / Side / Angled) — mapped accurately below.
--   * Other SKUs only publish colourway photos on the storefront, not
--     distinct left/right angles. For those, view_images is best-effort:
--     front is the real primary image; remaining slots reuse the available
--     photos. Swap in proper 4-angle renders when available.
--   * pricing_slabs left empty — MadHats to provide volume pricing (OQ-03).
-- =========================================================================

delete from product_references;
delete from stores;

-- Default tenant. public_key is the X-Store-Key the storefront widget sends.
insert into stores
  (id, slug, name, public_key, shopify_domain, allowed_origins,
   persona_name, greeting_template, sales_notification_email)
values (
  'a0000000-0000-0000-0000-000000000001',
  'madhats',
  'MadHats',
  'mh_pk_madhats_local',
  'madhats.com.au',
  array['http://localhost:5173','http://127.0.0.1:5173','https://www.madhats.com.au'],
  'Ricardo',
  'Hi {name}, I''m Ricardo — MadHats'' AI design assistant. Let me help you get the perfect look.',
  'sales@madhats.com.au'
);

insert into product_references
  (id, shopify_product_id, style, colour, name, description, store_url,
   reference_image_url, view_images, placement_zones, decoration_types)
values
-- 1. A Frame Flex Cap — premium 6-panel snapback (TRUE 4-angle views) --------
(
  '11111111-1111-1111-1111-111111111111',
  'a-frame-flex-copy',
  'snapback',
  'Black & White',
  'A Frame Flex Cap',
  'A premium 6-panel snapback built for everyday wear. Structured crown, curved brim and durable cotton twill, with a flex fit band for all-day comfort.',
  'https://www.madhats.com.au/products/a-frame-flex-copy',
  'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/FlexBCap_Front.png',
  jsonb_build_object(
    'front', 'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/FlexBCap_Front.png',
    'back',  'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/FlexBCap_Back.png',
    'left',  'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/FlexBCap_Side.png',
    'right', 'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/FlexBCap_Angled.png'
  ),
  array['front_panel','side','back','under_brim'],
  array['print','embroidery']
),

-- 2. Flex Kindy Bucket Hat — kids bucket (colourway photos) ------------------
(
  '22222222-2222-2222-2222-222222222222',
  'flex-kindy-bucket-hat-1',
  'bucket_hat',
  'Navy',
  'Flex Kindy Bucket Hat',
  'A soft, breathable bucket hat sized for little ones. Perfect sun protection for kindy and outdoor adventures, with a flexible fit across sizes 50-58.',
  'https://www.madhats.com.au/products/flex-kindy-bucket-hat-1',
  'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/flex-kindy-bucket-hat-795636_96d443e8-7df8-4c8c-8f59-2fa0b92e7eef.jpg',
  jsonb_build_object(
    'front', 'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/flex-kindy-bucket-hat-795636_96d443e8-7df8-4c8c-8f59-2fa0b92e7eef.jpg',
    'back',  'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/flex-kindy-bucket-hat-739453_c58d06a3-979a-4ced-bc59-7bde805e26c6.jpg',
    'left',  'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/flex-kindy-bucket-hat-652676_0654343c-5de1-4706-8412-2f46918f66f1.jpg',
    'right', 'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/flex-kindy-bucket-hat-962907_93671417-3f57-47f6-9721-4dba3a8dee0c.jpg'
  ),
  array['front_panel','side'],
  array['print','embroidery']
),

-- 3. AH245 Owen Cap — classic basic cap -------------------------------------
(
  '33333333-3333-3333-3333-333333333333',
  'ah245-owen-cap',
  'baseball_cap',
  'Navy / White',
  'AH245 Owen Cap',
  'A classic, versatile baseball cap made from high-quality materials. Comfortable structured fit that suits casual and uniform wear alike.',
  'https://www.madhats.com.au/products/ah245-owen-cap',
  'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/owen-cap-147284.jpg',
  jsonb_build_object(
    'front', 'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/owen-cap-147284.jpg',
    'back',  'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/owen-cap-845277.jpg',
    'left',  'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/owen-cap-137030.webp',
    'right', 'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/owen-cap-147284.jpg'
  ),
  array['front_panel','side','back'],
  array['print','embroidery']
),

-- 4. AH334 Brennan Cap — structured 6 panel ---------------------------------
(
  '44444444-4444-4444-4444-444444444444',
  'ah334-brennan-cap',
  'structured_6panel',
  'Red / Black',
  'AH334 Brennan Cap',
  'Structured 6-panel cap with a pre-curved peak. Contrast stitching on seam tape, stretchable fabric and a hook-and-loop closure for an adjustable fit.',
  'https://www.madhats.com.au/products/ah334-brennan-cap',
  'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/brennan-cap-584595.jpg',
  jsonb_build_object(
    'front', 'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/brennan-cap-584595.jpg',
    'back',  'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/brennan-cap-584595.jpg',
    'left',  'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/brennan-cap-584595.jpg',
    'right', 'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/brennan-cap-584595.jpg'
  ),
  array['front_panel','side','back'],
  array['print','embroidery']
),

-- 5. AH328 Sab Cap — high-profile trucker with mesh -------------------------
(
  '55555555-5555-5555-5555-555555555555',
  'ah328-sab-cap',
  'trucker',
  'Fluoro Orange',
  'AH328 Sab Cap',
  'High-profile 6-panel cap with a pre-curved peak and comfort-mesh side panels. Hook-and-loop closure. A breathable pick for high-visibility branding.',
  'https://www.madhats.com.au/products/ah328-sab-cap',
  'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/sab-cap-606915.jpg',
  jsonb_build_object(
    'front', 'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/sab-cap-606915.jpg',
    'back',  'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/sab-cap-606915.jpg',
    'left',  'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/sab-cap-606915.jpg',
    'right', 'https://cdn.shopify.com/s/files/1/0376/4849/8824/products/sab-cap-606915.jpg'
  ),
  array['front_panel','side'],
  array['print','embroidery','patch']
),

-- 6. AH142 Mamba Cap — structured 6 panel, flat peak ------------------------
(
  '66666666-6666-6666-6666-666666666666',
  'ah142-mamba-cap',
  'structured_6panel',
  'Fluoro Green / Black',
  'AH142 Mamba Cap',
  'Structured 6-panel cap with a flat peak. A bold, sporty silhouette suited to motorsport, school and event teams.',
  'https://www.madhats.com.au/products/ah142-mamba-cap',
  'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/AH142_Fluro-Green_Black__32804-600x600.jpg',
  jsonb_build_object(
    'front', 'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/AH142_Fluro-Green_Black__32804-600x600.jpg',
    'back',  'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/AH142_Digital-Camo-Grey__39497-600x600.jpg',
    'left',  'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/AH142_Fluro-Orange_Black__89261-600x600.jpg',
    'right', 'https://cdn.shopify.com/s/files/1/0376/4849/8824/files/AH142_Fluro-Green_Black__32804-600x600.jpg'
  ),
  array['front_panel','side','back'],
  array['print','embroidery']
);

-- Scope every seeded product to the default MadHats tenant.
update product_references
   set store_id = 'a0000000-0000-0000-0000-000000000001'
 where store_id is null;
