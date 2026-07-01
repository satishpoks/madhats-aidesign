# Fidelity-Locked Image Generation Prompt + Prompt-Preview Debug Endpoint

**Date:** 2026-07-01
**Status:** Approved (brainstorm)
**Owner:** Backend

## Problem

Generated previews drift from the selected product: the cap's colour, shape,
strap, and construction change instead of staying identical to the reference
photo. The current `IMAGE_GEN_BASE_TEMPLATE` states the preserve-the-cap rule in
a single soft sentence and only interpolates `design_summary`, ignoring the rest
of the extracted design intent (`colours`, `text_elements`, `imagery`, `style`).
Gemini image models follow explicit, enumerated, imperative instructions much
more reliably than a soft paragraph.

There is also no easy way to see the exact prompt string sent to Gemini, which
makes tuning slow.

## Hard constraint (unchanged)

Per `CLAUDE.md` §2: always composite onto the real product reference photo; never
generate a cap from scratch. This design tightens that constraint, it does not
relax it.

## Decisions

1. **Base cap is always locked to the reference.** Cap type, silhouette, crown
   shape, panel count, seams, body colour(s), brim, back strap/closure, eyelets,
   labels, fabric texture, camera angle, lighting, and background are reproduced
   pixel-faithfully from the first image. The customer only **adds decoration**.
   Changing the cap colour is done by selecting a different colourway (a
   different reference photo), never by asking the model to recolour the cap.
   There is no per-product "customisable" flag in this scope.

2. **Deliverable = one readable template + an admin debug endpoint.** The full
   prompt lives as a single consolidated, editable template in `app/prompts.py`;
   a new admin-gated route returns the exact final assembled prompt for a session
   without generating an image.

## Design

### 1. New consolidated prompt template (`app/prompts.py`)

Replace `IMAGE_GEN_BASE_TEMPLATE` + `PLACEMENT_CONTEXT_TEMPLATE` with a single
`IMAGE_GEN_PROMPT` template. The embroidery/print modifiers and the pin template
are kept (tightened). Placeholders: `{decoration_kind}`, `{design_block}`,
`{decoration_style}`, `{placement_zone}`, `{placement_position}`, `{pin_block}`.

```
ROLE: You composite a single custom decoration onto a REAL product photograph.

SOURCE OF TRUTH: The FIRST image is the exact cap to reproduce. Treat it as a
fixed product photo that already shows the correct product, colourway and angle.

PRIMARY DIRECTIVE — REPRODUCE THE CAP EXACTLY.
Everything about the cap MUST stay pixel-identical to the first image. Do NOT
alter any of the following:
  • Cap type/style and overall silhouette
  • Crown shape, panel count, seams and stitching
  • Cap body colour(s) and any colour-blocking — keep the EXACT colours shown
  • Brim/peak shape, colour and under-brim colour
  • Back closure / strap (snapback, velcro, buckle, elastic) — same type & colour
  • Eyelets, top button, sweatband, woven labels and tags
  • Fabric texture, sheen and folds
  • Camera angle, framing, crop, lighting, shadows and background

Do NOT recolour, reshape, restyle, re-light, rotate, crop or re-render the cap.
Do NOT add any logo, text, pattern or embellishment that is not specified below.
Do NOT add a person, model or new background.

THE ONLY PERMITTED CHANGE:
Add the decoration described below onto the specified panel, as though it were
{decoration_kind} applied to this exact cap. Nothing else changes.

DECORATION TO ADD:
{design_block}

DECORATION STYLE:
{decoration_style}

PLACEMENT:
On the {placement_zone}, positioned {placement_position}. Follow the panel's
natural curvature, perspective and lighting so it looks physically applied.
{pin_block}

OUTPUT: One photorealistic image of the SAME cap from the SAME angle as the
reference, identical in every respect except for the added decoration.
```

- `{decoration_kind}` = `"stitched embroidery"` (embroidery) or `"a printed graphic"` (print).
- `{decoration_style}` = existing `EMBROIDERY_STYLE_MODIFIER` / `PRINT_STYLE_MODIFIER`.
- `{pin_block}` = joined `PIN_ANNOTATION_TEMPLATE` lines, or empty string.

### 2. `build_prompt` changes (`app/services/prompt_builder.py`)

Assemble `design_block` from the session's design intent:

- **Flow B — uploaded logo present** (`collected.uploaded_asset_path` truthy):
  `design_block` = "Apply the customer's uploaded artwork, provided as the SECOND
  image. Reproduce that artwork faithfully — exact colours, proportions and
  detail. Do not redraw, reinterpret or restyle it." (If a one-line summary was
  also captured, append it as extra context.)

- **Flow A — described design**: build a structured block from the full
  `design_description` dict:
  - `summary` → lead line.
  - `text_elements` → `Text to include (render exactly as written): "A", "B"`.
  - `colours` → `Design colours: ...` (explicitly the decoration's colours, not
    the cap's).
  - `imagery` → `Graphics/icons: ...`.
  - `style` → `Design style: ...`.
  Omit any field that is empty. Fallback when nothing is captured: "the
  customer's supplied design".

The function remains pure and composable so the cache key (`prompt_hash`) and the
debug endpoint both operate on the same assembled string. No change to
`build_params`, `prompt_hash`, or the caller in `generate.py`.

### 3. Prompt-preview debug endpoint

New router `app/api/routes/admin_prompt.py`:

`GET /admin/prompt-preview/{session_id}?tier=preview|final`
- Gated by `Depends(require_admin)` (X-Admin-Secret), same as the other admin routers.
- Loads the session; 404 if not found; 400 if the session has no product
  reference image (same guard as generation).
- Rebuilds `params` + `prompt` via `prompt_builder`, resolves the provider via
  `get_provider(tier)` for reporting only (no `.generate()` call).
- Returns JSON:

```json
{
  "session_id": "...",
  "tier": "preview",
  "provider": "GeminiFlashAdapter",
  "model": "gemini-2.5-flash-image",
  "reference_image_url": "https://...",
  "has_uploaded_asset": false,
  "prompt": "<exact final string sent to Gemini>"
}
```

No image generation, no cost. Registered in `app/main.py` alongside the other
admin routers. `model` is best-effort (the provider may expose `model_name`);
fall back to the configured env value or `null`.

### 4. Testing

- `tests/test_prompt_builder.py` (new/extended):
  - Cap-lock directive lines are always present regardless of inputs.
  - Flow B: references "SECOND image" and does not fabricate a described design.
  - Flow A: `text_elements`, `colours`, `imagery`, `style` all appear; empty
    fields are omitted.
  - Embroidery vs print selects the correct `{decoration_kind}` + modifier.
  - Pins are appended; no pins → no pin block.
  - Missing reference image raises `PromptBuildError`.
- `tests/test_admin_prompt.py` (new):
  - 401/403 without the admin secret.
  - 200 + `prompt` string (containing the cap-lock directive) with the secret.
  - 404 for an unknown session.

## Out of scope

- Per-product "customisable" flag / model-driven cap recolouring.
- Any change to the caching behaviour, delivery, or email pipeline.
- Frontend changes.

## Acceptance

- A generated preview keeps the exact selected cap (colour/shape/strap) and shows
  only the requested decoration.
- `GET /admin/prompt-preview/{session_id}` returns the exact prompt with the admin
  secret, 401/403 without it.
- Full backend `pytest` suite green.
