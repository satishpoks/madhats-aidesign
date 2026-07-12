"""Single source of truth for every prompt and email-body string.

Nothing that is sent to an AI model or used as an email template is written
inline anywhere else in the codebase. Import from here.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Ricardo system prompt
# ---------------------------------------------------------------------------

RICARDO_SYSTEM_PROMPT = """You are Ricardo, MadHats' friendly AI design assistant.
MadHats is an Australian custom headwear and printing company.

Your role:
- Guide customers through designing custom caps in a warm, concise, consultative tone.
- You are NOT a salesperson — you help with design and capture contact details only.
- Keep replies short (1-3 sentences). Sound human, never robotic or form-like.
- Warm, understated Australian professionalism. Do NOT pepper messages with "G'day" or heavy slang.

Hard rules:
- Greet the customer only ONCE, in your very first message. NEVER open a later message
  with a greeting — no "G'day", "Hi", "Hey", "Hello", or the customer's name as a salutation.
  After the first message, continue as if mid-conversation and get straight to the point.
- Vary your wording between turns. Don't reuse the same opener or the same acknowledgement
  ("Great!", "Perfect!") every message.
- Never invent prices or commit to a quote. A human salesperson handles quoting.
- Never ask the customer to upload a photo of their face.
- Stay on the current step. Do not skip ahead or ask multiple questions at once.
"""

# ---------------------------------------------------------------------------
# Per-state response templates (Haiku fills these into natural language)
# Keyed by ConversationState value.
# ---------------------------------------------------------------------------

STATE_PROMPTS: dict[str, str] = {
    "greeting": "Greet the customer warmly as Ricardo and ask for their first name.",
    "ask_name": "Ask the customer for their first name.",
    "ask_purpose": "Address the customer by name ({name}) and ask what the hats are for "
    "(e.g. gift, staff uniforms, resale, event giveaway, personal use).",
    "check_youth": "Acknowledge the purpose and move things along briefly.",
    "youth_referral": "Warmly note that youth/school orders are handled by a specialist "
    "and that you'll still help them design something now.",
    "ask_quantity": "Ask roughly how many hats they're thinking of ordering.",
    "decoration_engine": "Briefly say you're working out the best decoration option.",
    "warn_print_setup": "Gently note that for a single hat, print is the most cost-effective "
    "option since embroidery has a setup fee. Ask if that sounds good.",
    "recommend_decoration": "Recommend print or embroidery for their quantity ({quantity}) "
    "and ask if that works for them.",
    "recommend_embroidery": "Recommend embroidery for their larger order ({quantity}) as it "
    "looks premium and is cost-effective at volume. Ask if that works.",
    "confirm_decoration": "Confirm the chosen decoration type ({decoration_type}) and move on.",
    "ask_has_logo": "Ask whether they have a logo or artwork to add, or if they'd prefer to "
    "describe what they want instead.",
    "upload_logo": "Invite them to upload their logo or artwork now.",
    "ask_remove_bg": "Ask if they'd like the background removed from their logo for a cleaner look.",
    "describe_design": "Invite them to describe the design they have in mind, in their own words.",
    "save_progress_email": (
        "Ask for the customer's email, explaining it saves their progress so they "
        "can return to this design anytime and lets you send the finished design "
        "when it's ready. One or two warm sentences — not pushy."
    ),
    "ask_more_elements": (
        "Ask whether the customer wants to add another element — text, a graphic, "
        "or a note for the team — making clear they can also say they're done. "
        "One or two sentences."
    ),
    "element_deepdive": (
        "You are taking a custom order like a helpful salesperson. Acknowledge what "
        "the customer just gave for the current element, then ask ONLY for the next "
        "detail (provided to you), making clear they can say 'you choose'. One or two "
        "sentences, warm and specific."
    ),
    "add_elements_mode": (
        "Acknowledge the element the customer just added (see the brief in "
        "context), then ask if they'd like to add anything else or are ready "
        "for you to place the design and generate it. One or two sentences."
    ),
    "ask_placement_zone": "Ask where they'd like the design placed: front panel, side, back, "
    "or under the brim.",
    "ask_placement_position": "Ask for the precise position within the {placement_zone} "
    "(left, centre or right; upper, middle or lower).",
    "ask_pin_annotation": "Ask if they'd like to drop a pin on the cap to add a specific note "
    "about placement, or skip and generate now.",
    "pin_annotate_mode": "Acknowledge the pin note and ask if they want to add another or finish.",
    "ask_hat_colour": "Ask what colour they'd like the hat itself to be.",
    "composite_preview": "Tell them here's a quick on-screen mock-up of the design across "
    "all four angles, and ask if it looks right to generate or they'd like to tweak something.",
    "generating": "Tell them you're putting the design together now and it'll be in "
    "their inbox and on-screen the moment it's ready. Do NOT ask for their email.",
    "ask_email": "Politely ask for their email so you can send the finished design.",
    "verify_email": "Let them know you've sent a quick verification email and ask them to click "
    "the link to confirm. Mention to check spam.",
    "email_verified": "Warmly confirm their email is now verified and let them know their "
    "design is on its way to their inbox for review.",
    "send_preview_email": "Let them know their design is ready and on its way to their inbox.",
    "show_design": "Tell them their design is ready and shown on screen (watermarked preview).",
    "offer_refine": "Ask if they'd like to tweak anything about the design, or if they're happy with it.",
    "describe_changes": "Invite them to describe the change they'd like to the design.",
    "regenerating": "Let them know you're updating the design with their changes now.",
    "quote_requested": "Let them know one of the MadHats team will be in touch with a quote shortly.",
    "upsell_prompt": "Warmly ask if they'd like to add the design to another part of the cap, "
    "such as the side panel or under the brim.",
    "session_end": "Thank them warmly by name ({name}) and wish them well.",
}

# ---------------------------------------------------------------------------
# Intent extraction prompts
# ---------------------------------------------------------------------------

BACKTRACK_DETECTION_PROMPT = """The customer is in the conversation step "{current_state}".
Their message: "{message}"

Decide whether they are trying to GO BACK / change a previous answer (e.g. "go back",
"actually change the quantity", "wait, I picked the wrong colour").

Allowed back-track target steps: {allowed_targets}

Respond with ONLY a JSON object:
- If backtracking: {{"backtrack": true, "target": "<one of the allowed targets>"}}
- If not: {{"backtrack": false, "target": null}}
"""

QUANTITY_EXTRACTION_PROMPT = """Extract the number of hats from this message: "{message}"

Handle freeform text: "a dozen" = 12, "twelve" = 12, "couple" = 2, "a few" = 3,
"50-99" = pick the lower bound 50, "not sure" = 0.

Respond with ONLY a JSON object: {{"quantity": <integer>}}
"""

YOUTH_DETECTION_PROMPT = """Does this message mention the hats being for children, kids, youth,
a school, a sports team of minors, or anyone under 18? Message: "{message}"

Respond with ONLY a JSON object: {{"youth": true}} or {{"youth": false}}
"""

DESIGN_EXTRACTION_PROMPT = """The customer described the design they want for a custom cap.
Message: "{message}"

Extract structured design context. Respond with ONLY a JSON object:
{{
  "summary": "<one-line description>",
  "colours": ["<colour>", ...],
  "text_elements": ["<any text/wording on the cap>", ...],
  "style": "<e.g. minimalist, bold, vintage, sporty>",
  "imagery": ["<icons/graphics described>", ...]
}}
Use empty arrays/strings for anything not mentioned.
"""

TURN_INTERPRETER_PROMPT = """You interpret one customer message in a guided cap-design chat.
You do NOT decide what happens next — you only classify the message and extract data.

Current step: "{current_state}" (the question just asked).
Fields we may extract (only include ones the customer actually gave):
  name, purpose, quantity (integer), decoration_type (embroidery|print|patch),
  has_logo (bool), remove_bg (bool), design_description (short string),
  placement_zone (front_panel|side|back|under_brim), placement_position (string).

Known so far (JSON): {collected}
Allowed "go back" steps: {allowed_targets}
Store FAQ / knowledge (use ONLY this to answer questions; never invent prices,
turnaround or stock — if it isn't covered, leave question_answer empty):
{faq}

Customer message: "{message}"

Classify intent:
- "answer": a direct answer to the current step.
- "provide_info": gives info for this and/or later steps (extract all of it).
- "ask_question": asks us something (fill question_answer from the FAQ, or "").
- "revise": wants to change an earlier answer (set revise_target to an allowed step).
- "chitchat": off-topic / unclear.
- "backtrack": explicitly wants to go back (set backtrack_target to an allowed step).

Respond with ONLY a JSON object:
{{
  "intent": "...",
  "fields": {{ ... }},
  "revise_target": null,
  "backtrack_target": null,
  "question_answer": "",
  "on_topic": true
}}
"""

REPLY_GENERATION_PROMPT = """Current step instruction: {state_instruction}

Known details so far (JSON): {collected}

Write Ricardo's next message to the customer. Follow the step instruction exactly,
stay in persona, keep it to 1-3 short sentences. Do not ask anything beyond this step.
Return ONLY the message text, no quotes or labels.
"""

# ---------------------------------------------------------------------------
# Per-element deep-dive: attribute extraction + dynamic "ask_for" wording
# ---------------------------------------------------------------------------

DEFER_WORDS = ("you choose", "your choice", "whatever", "you decide", "team decide",
               "surprise me", "no preference", "don't mind", "dont mind", "any", "up to you")

ATTRIBUTE_QUESTIONS = {
    "content": "What would you like it to say?",
    "font": "What font feel would you like — bold, classic, handwritten? (or say 'you choose')",
    "size": "Roughly how big — small, medium or large? (or 'you choose')",
    "colour": "What colour should it be? (or 'you choose')",
    "style": "Any special styling — an outline, a shadow, or curved text? (or 'none')",
    "placement_zone": "Where on the cap should this go — front, side, back, or under the brim?",
    "placement_position": "Whereabouts there — left, centre or right?",
    "remove_bg": "Should I clean up / remove the background of your artwork? (yes/no)",
}

ELEMENT_ATTRIBUTE_PROMPT = """The customer is describing ONE decoration element of type "{el_type}" for a cap.
Message: "{message}"
Extract ONLY attributes they actually gave. Respond with ONLY a JSON object with any of:
{{"content": "...", "font": "...", "size": "small|medium|large", "colour": "...",
  "style": "...", "placement_zone": "front_panel|side|back|under_brim",
  "placement_position": "left|centre|right", "remove_bg": true, "defer": true}}
Set "defer": true if they said to leave it to you (e.g. "you choose"). Omit anything not mentioned."""

# ---------------------------------------------------------------------------
# Canned replies — user-facing, no LLM required
#
# Used when settings.anthropic_api_key is empty (local dev / CI).
# Keyed by ConversationState value. Placeholders: {name}, {quantity},
# {decoration_type}, {placement_zone}, {persona}.
# NEVER return the STATE_PROMPTS templates to the user — those are
# Haiku-instruction strings, not user-facing text.
# ---------------------------------------------------------------------------

CANNED_REPLIES: dict[str, str] = {
    "greeting": (
        "Hi there! I'm {persona}, MadHats' AI design assistant — "
        "I'm here to help you create something awesome. What's your first name?"
    ),
    "ask_name": "What's your first name? I'd love to make this feel a bit more personal!",
    "ask_purpose": (
        "Great to meet you, {name}! What are the hats for — "
        "staff uniforms, an event, a gift, personal use, or something else?"
    ),
    "check_youth": "Got it — just working out the best option for you.",
    "youth_referral": (
        "That sounds like a great project! Youth and school orders have a dedicated specialist, "
        "but let's design something awesome together now anyway."
    ),
    "ask_quantity": "Roughly how many hats are you thinking? Even a ballpark helps.",
    "decoration_engine": "Let me work out the best decoration option for your order.",
    "warn_print_setup": (
        "For a single hat, print is the most cost-effective choice since embroidery has a setup fee. "
        "Does that sound good?"
    ),
    "recommend_decoration": (
        "For {quantity} hats, I'd recommend print — it looks sharp and keeps costs down. "
        "Does that work for you?"
    ),
    "recommend_embroidery": (
        "For {quantity} hats, embroidery is the way to go — it looks premium "
        "and is great value at that volume. Happy with that?"
    ),
    "confirm_decoration": "Perfect, we'll go with {decoration_type}. Now let's talk design!",
    "ask_has_logo": (
        "Do you have a logo or artwork you'd like to use, "
        "or would you prefer to describe what you have in mind?"
    ),
    "upload_logo": "Go ahead and upload your logo or artwork file whenever you're ready.",
    "ask_remove_bg": (
        "Would you like me to remove the background from your logo for a cleaner result?"
    ),
    "describe_design": (
        "Tell me about the design you have in mind — colours, text, graphics, vibe — "
        "whatever comes to mind!"
    ),
    "save_progress_email": (
        "What's the best email for you? I'll save your progress so you can pick this "
        "design back up anytime — and send the finished design across once it's ready."
    ),
    "ask_more_elements": (
        "Anything to add — some text, a graphic, or a note for our team? "
        "Or say 'that's everything' and I'll put it together."
    ),
    "element_deepdive": "Great — let's nail down the details of that one.",
    "add_elements_mode": (
        "Got it — I've added that. Anything else you'd like on there, or shall "
        "I place the design and generate it?"
    ),
    "ask_placement_zone": (
        "Where would you like the design placed? "
        "Front panel, side, back, or under the brim?"
    ),
    "ask_placement_position": (
        "And where exactly on the {placement_zone}? "
        "Left, centre or right — and upper, middle or lower?"
    ),
    "ask_pin_annotation": (
        "Would you like to drop a pin on the cap to mark exactly where the design should go, "
        "or skip straight to generating?"
    ),
    "pin_annotate_mode": "Got that pin! Want to add another, or are you ready to generate?",
    "ask_hat_colour": "What colour would you like the hat itself to be?",
    "composite_preview": (
        "Here's a quick mock-up of your design across the front, back and sides. "
        "Happy for me to generate it, or would you like to tweak something?"
    ),
    "generating": (
        "Putting your design together now — I'll pop it in your inbox and "
        "on-screen the moment it's ready."
    ),
    "ask_email": "What's the best email address to send your design to?",
    "verify_email": (
        "I've sent a quick verification to your inbox — just click the link to confirm. "
        "Check your spam folder if you don't see it!"
    ),
    "email_verified": "Your email's verified — thank you! Your design is on its way to your "
    "inbox now for review.",
    "send_preview_email": "Your design is on its way to your inbox now.",
    "show_design": "Here's your design — take a look on the left! It's a watermarked preview.",
    "offer_refine": "Want to tweak anything about it, or are you happy with this design?",
    "describe_changes": "Sure — tell me what you'd like to change and I'll update it.",
    "regenerating": "Updating your design with those changes now…",
    "quote_requested": "One of the MadHats team will be in touch with your quote shortly.",
    "upsell_prompt": (
        "Looking great! Would you like to add the design to another part of the cap, "
        "such as the side panel or under the brim?"
    ),
    "session_end": "Thanks so much, {name}! It was great designing with you. The MadHats team will be in touch soon.",
}

# ---------------------------------------------------------------------------
# Image generation prompt templates
# ---------------------------------------------------------------------------

# The one consolidated image-generation prompt. Assembled by
# app.services.prompt_builder.build_prompt, which fills every {placeholder}.
# Edit the wording here to tune generation; inspect the exact filled result for a
# session via GET /admin/prompt-preview/{session_id}.
#
# Design intent: the base cap must be reproduced pixel-faithfully from the
# reference photo (first image). The customer only ADDS decoration. See
# docs/superpowers/specs/2026-07-01-fidelity-locked-image-prompt-design.md.
IMAGE_GEN_PROMPT = """ROLE: You composite a single custom decoration onto a REAL product photograph.

SOURCE OF TRUTH: The FIRST image is the exact cap to reproduce. Treat it as a
fixed product photo that already shows the correct product, colourway and angle.

PRIMARY DIRECTIVE — REPRODUCE THE CAP EXACTLY.
Everything about the cap MUST stay pixel-identical to the first image. Do NOT
alter any of the following:
  - Cap type/style and overall silhouette
  - Crown shape, panel count, seams and stitching
  - Cap body colour(s) and any colour-blocking — keep the EXACT colours shown
  - Brim/peak shape, colour and under-brim colour
  - Back closure / strap (snapback, velcro, buckle, elastic) — same type & colour
  - Eyelets, top button, sweatband, woven labels and tags
  - Fabric texture, sheen and folds
  - Camera angle, framing, crop, lighting, shadows and background

Do NOT recolour, reshape, restyle, re-light, rotate, crop or re-render the cap.
Do NOT add any logo, text, pattern or embellishment that is not specified below.
Do NOT add a person, model or new background.

THE ONLY PERMITTED CHANGE:
Add the decoration described below onto the specified panel, as though it were
{decoration_kind} applied to this exact cap. Nothing else changes.

DECORATION(S) TO ADD (each placed exactly as noted):
{design_block}

DECORATION STYLE:
Every added decoration must follow the panel's natural curvature, perspective and lighting so it looks physically applied, not like a flat sticker.
{decoration_style}
{pin_block}

OUTPUT — STRICT:
Return ONE photorealistic, SQUARE (1:1 aspect ratio) image of the SAME single cap
from the SAME angle as the reference, identical in every respect except for the
added decoration. The cap must be centred and fill roughly 70-75% of the frame on
a plain, uncluttered background.
Render NOTHING ELSE. Absolutely no title, caption, heading, label, product name,
design name, customer name, watermark, text card, or any words that are not part
of the decoration itself; and no second panel, collage, split-screen,
side-by-side, grid, multi-panel, before/after, duplicate cap, reference swatch,
logo copy, or second image of any kind. The result is a single product photo of
one cap and nothing more."""

# design_block for Flow B (customer uploaded a logo/artwork — the 2nd image).
UPLOADED_ASSET_DESIGN_BLOCK = """Apply the customer's uploaded artwork, provided as the SECOND image, ONTO the cap.
Reproduce that artwork faithfully — exact colours, proportions and detail. Do not
redraw, reinterpret or restyle it.
The SECOND image is a REFERENCE for the decoration only. Do NOT reproduce it as a
separate standalone element anywhere in the output — no side panel, tile, sticker,
swatch, framed copy or floating duplicate, and never on its own background. The
uploaded artwork may appear ONLY as decoration on the cap panel, nowhere else."""

# Fallback design_block when no design intent was captured at all.
FALLBACK_DESIGN_BLOCK = "the customer's supplied design"

# {decoration_kind} values interpolated into IMAGE_GEN_PROMPT.
DECORATION_KIND_EMBROIDERY = "stitched embroidery"
DECORATION_KIND_PRINT = "a printed graphic"

EMBROIDERY_STYLE_MODIFIER = """Render the decoration as realistic stitched EMBROIDERY: visible
thread texture, slight raised relief, satin-stitch edges, matte thread sheen. No flat print look."""

PRINT_STYLE_MODIFIER = """Render the decoration as a flat screen-PRINT / heat-transfer: smooth,
flat colour application that follows the fabric texture. No raised stitching."""

PIN_ANNOTATION_TEMPLATE = """Customer placement note on the {view} view at approximately
({x_pct}%, {y_pct}%): "{comment}"."""

# ---------------------------------------------------------------------------
# Email body templates
# ---------------------------------------------------------------------------

VERIFICATION_EMAIL_SUBJECT = "Confirm your email to see your MadHats design"

VERIFICATION_EMAIL_BODY = """Hi {name},

Thanks for designing with MadHats! Please confirm your email so we can send your
design across:

{verify_url}

This link expires in 15 minutes. If you didn't request this, you can ignore this email.

— Ricardo, MadHats AI Design Studio
"""

PREVIEW_EMAIL_SUBJECT = "Your MadHats design is ready to review 🎉"

FINAL_DESIGN_EMAIL_SUBJECT = "Your updated MadHats design 🎉"

# One-line brief echoed back to the customer in the preview email.
# Filled with .format(product=, decoration=, placement=, quantity=).
PREVIEW_EMAIL_BRIEF = (
    "Your custom cap design is ready to review. We've put together a preview "
    "based on your brief — {product}, {decoration}, {placement} placement, {quantity} pieces."
)

# HTML preview email — mirrors the Figma "E1 — Email Template (Design Delivery)"
# frame (node 22:2). Email-client-safe: table layout + inline styles only, no
# flexbox/absolute positioning. Uses string.Template ($placeholders) so the
# inline CSS braces don't need escaping. All interpolated values are
# HTML-escaped by the caller (app.services.email).
PREVIEW_EMAIL_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Your MadHats design</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr><td style="background:#ff5c00;padding:14px 24px;">
          <div style="font-size:22px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">MAD HATS</div>
          <div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>
        </td></tr>
        <tr><td style="padding:28px 32px 0 32px;">
          <div style="font-size:20px;font-weight:bold;color:#1a1a2e;">Hi $name,</div>
          <p style="font-size:13px;line-height:20px;color:#6b6b80;margin:12px 0 0 0;">$brief</p>
        </td></tr>
        <tr><td style="padding:24px 32px 0 32px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fcf7f2;border:2px solid #ff5c00;border-radius:12px;">
            <tr><td align="center" style="padding:16px;">
              <img src="$image_url" alt="Your MadHats design preview" width="100%" style="display:block;width:100%;max-width:504px;border-radius:8px;" />
              <div style="margin-top:10px;font-size:10px;color:#9e9eab;">Watermarked preview</div>
            </td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:24px 32px 0 32px;">
          <hr style="border:none;border-top:1px solid #e0e1ea;margin:0;" />
        </td></tr>
        <tr><td style="padding:16px 32px 0 32px;">
          <div style="font-size:18px;font-weight:bold;color:#1a1a2e;">What would you like to do?</div>
          <p style="font-size:13px;color:#6b6b80;margin:8px 0 0 0;">Choose an option below — our team is ready to help.</p>
        </td></tr>
        <tr><td style="padding:20px 32px 0 32px;">
          <a href="$quote_url" style="display:block;background:#ff5c00;color:#ffffff;text-decoration:none;text-align:center;font-weight:bold;font-size:15px;padding:16px;border-radius:10px;box-shadow:0 4px 12px rgba(255,92,0,0.35);">&#10003;&nbsp;&nbsp;Yes, I love it — request a quote</a>
        </td></tr>
        <tr><td style="padding:12px 32px 0 32px;">
          <a href="$edit_url" style="display:block;background:#ffffff;border:1.5px solid #ff5c00;color:#bf2e00;text-decoration:none;text-align:center;font-weight:bold;font-size:15px;padding:14px;border-radius:10px;">&#9998;&nbsp;&nbsp;I'd like to make some edits</a>
        </td></tr>
        <tr><td style="padding:12px 32px 0 32px;">
          <a href="$talk_url" style="display:block;background:#f3f4f6;border:1px solid #e0e1ea;color:#6b6b80;text-decoration:none;text-align:center;font-size:13px;padding:14px;border-radius:10px;">&#128172;&nbsp;&nbsp;Talk to our team for more customisation options</a>
        </td></tr>
        <tr><td style="padding:24px 32px 28px 32px;">
          <hr style="border:none;border-top:1px solid #e0e1ea;margin:0 0 16px 0;" />
          <div style="font-size:12px;color:#9e9eab;">— Ricardo, MadHats AI Design Studio</div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

SALES_QUOTE_EMAIL_SUBJECT = "New design lead: {product_name} x{quantity}"

SALES_QUOTE_EMAIL_BODY = """New verified design lead from the AI Design Studio.

Customer: {customer_name}
Email: {customer_email}
Phone: {customer_phone}

Product: {product_name} ({product_style}, {product_colour})
Quantity: {quantity}
Decoration: {decoration_type}
Placement: {placement_zone} / {placement_position}

Design details:
{design_brief}

Design image (internal, clean): {image_url}

Please prepare and send the quote directly to the customer.
"""

# Sent to store ops when a customer explicitly confirms their design and requests
# a quote via the emailed quote link (distinct from the auto delivery-time
# heads-up in SALES_QUOTE_EMAIL_BODY). This is the "hot lead" — they've seen the
# design, confirmed the details, and asked us to quote.
SALES_QUOTE_CONFIRMED_EMAIL_SUBJECT = (
    "Customer confirmed — quote requested: {product_name} x{quantity}"
)

SALES_QUOTE_CONFIRMED_EMAIL_BODY = """The customer confirmed their design and requested a quote from the AI Design Studio.

Customer: {customer_name}
Email: {customer_email}
Phone: {customer_phone}
Wants phone/text follow-up: {notify_by_phone}

Product: {product_name} ({product_style}, {product_colour})
Quantity (confirmed): {quantity}
Decoration: {decoration_type}
Placement: {placement_zone} / {placement_position}

Design details:
{design_brief}

Customer note: {note}

Design image (internal, clean): {image_url}

Please verify the quote and send it directly to the customer.
"""

GENERATION_ALERT_EMAIL_SUBJECT = "Action needed: design generation failed — {product_name}"

# Sent to store ops when a generation fails all automatic retries. Filled with
# .format(session_id=, product_name=, brief=, error=). No customer name/email
# here — this is an internal ops alert, not a customer-facing message.
GENERATION_ALERT_EMAIL_BODY = """A design generation failed after all automatic retries and needs manual attention.

Session: {session_id}
Product: {product_name}
Design brief: {brief}

Provider error: {error}

Please regenerate this design from the admin tools. Once generation completes,
the customer's preview email will be sent automatically if their address is
already verified — no further action needed beyond regenerating.
"""

# ---------------------------------------------------------------------------
# Verification landing pages (rendered in the browser when the customer clicks
# the link in the verification email). These are HTML pages, not emails.
# IMPORTANT: the success page intentionally shows NO design image or preview —
# it only confirms the email and promises the design by email shortly.
# ---------------------------------------------------------------------------

VERIFICATION_SUCCESS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Email verified — MadHats</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" height="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;min-height:100vh;">
    <tr><td align="center" style="padding:40px 16px;">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr><td style="background:#ff5c00;padding:18px 28px;">
          <div style="font-size:20px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">MAD HATS</div>
          <div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>
        </td></tr>
        <tr><td style="padding:40px 28px;text-align:center;">
          <div style="font-size:44px;line-height:1;">&#9989;</div>
          <h1 style="font-size:22px;color:#1a1a2e;margin:18px 0 8px 0;">Your email is now verified</h1>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:0;">Thanks for confirming — we'll send your design across shortly. Keep an eye on your inbox.</p>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:12px 0 0 0;">You can close this page and head back to the chat.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

# Filled with .format(message=...) for expired / invalid / already-used links.
VERIFICATION_ERROR_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Verification problem — MadHats</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" height="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;min-height:100vh;">
    <tr><td align="center" style="padding:40px 16px;">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr><td style="background:#ff5c00;padding:18px 28px;">
          <div style="font-size:20px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">MAD HATS</div>
          <div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>
        </td></tr>
        <tr><td style="padding:40px 28px;text-align:center;">
          <div style="font-size:44px;line-height:1;">&#9888;&#65039;</div>
          <h1 style="font-size:22px;color:#1a1a2e;margin:18px 0 8px 0;">We couldn't verify that link</h1>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:0;">{message}</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Request-a-Quote pages (server-rendered, opened from the preview email's CTA).
# QUOTE_CONFIRM_HTML uses string.Template ($placeholders); the route HTML-escapes
# every interpolated value. QUOTE_IMAGE_BLOCK is substituted separately (or left
# empty when there's no image) and injected as $image_block.
# ---------------------------------------------------------------------------

QUOTE_IMAGE_BLOCK = """\
        <tr><td style="padding:20px 32px 0 32px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fcf7f2;border:2px solid #ff5c00;border-radius:12px;">
            <tr><td align="center" style="padding:14px;">
              <img src="$image_url" alt="Your MadHats design preview" width="100%" style="display:block;width:100%;max-width:504px;border-radius:8px;" />
              <div style="margin-top:8px;font-size:10px;color:#9e9eab;">$caption</div>
            </td></tr>
          </table>
        </td></tr>
"""

QUOTE_CONFIRM_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Request your quote — MadHats</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr><td style="background:#ff5c00;padding:16px 28px;">
          <div style="font-size:20px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">MAD HATS</div>
          <div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>
        </td></tr>
        <tr><td style="padding:28px 32px 0 32px;">
          <h1 style="font-size:22px;color:#1a1a2e;margin:0;">Request your quote</h1>
          <p style="font-size:13px;line-height:20px;color:#6b6b80;margin:10px 0 0 0;">Confirm your design details below and our team will put a quote together for you.</p>
        </td></tr>
$image_block
        <tr><td style="padding:20px 32px 0 32px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;color:#1a1a2e;">
            <tr><td style="padding:6px 0;color:#6b6b80;">Product</td><td style="padding:6px 0;text-align:right;font-weight:bold;">$product</td></tr>
            <tr><td style="padding:6px 0;color:#6b6b80;">Decoration</td><td style="padding:6px 0;text-align:right;font-weight:bold;">$decoration</td></tr>
            <tr><td style="padding:6px 0;color:#6b6b80;">Placement</td><td style="padding:6px 0;text-align:right;font-weight:bold;">$placement</td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:16px 32px 28px 32px;">
          <form method="post" action="$action_url">
            <label style="display:block;font-size:13px;color:#1a1a2e;font-weight:bold;margin:14px 0 4px 0;">How many hats?</label>
            <input type="number" name="quantity" value="$quantity" min="1" style="width:100%;box-sizing:border-box;padding:12px;border:1px solid #e0e1ea;border-radius:8px;font-size:15px;" />
            <label style="display:block;font-size:13px;color:#1a1a2e;font-weight:bold;margin:16px 0 4px 0;">Anything else we should know? (optional)</label>
            <textarea name="note" rows="3" style="width:100%;box-sizing:border-box;padding:12px;border:1px solid #e0e1ea;border-radius:8px;font-size:15px;"></textarea>
            <label style="display:block;font-size:13px;color:#1a1a2e;font-weight:bold;margin:16px 0 4px 0;">Phone number (optional)</label>
            <input type="tel" name="phone" placeholder="So a rep can reach you" style="width:100%;box-sizing:border-box;padding:12px;border:1px solid #e0e1ea;border-radius:8px;font-size:15px;" />
            <label style="display:flex;align-items:center;font-size:13px;color:#6b6b80;margin:12px 0 0 0;">
              <input type="checkbox" name="notify_by_phone" value="yes" style="margin-right:8px;" /> Text or call me when my quote's ready
            </label>
            <button type="submit" style="display:block;width:100%;margin-top:22px;background:#ff5c00;color:#ffffff;border:none;text-align:center;font-weight:bold;font-size:15px;padding:16px;border-radius:10px;cursor:pointer;box-shadow:0 4px 12px rgba(255,92,0,0.35);">Confirm &amp; request my quote</button>
          </form>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

QUOTE_SUCCESS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Quote requested — MadHats</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" height="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;min-height:100vh;">
    <tr><td align="center" style="padding:40px 16px;">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr><td style="background:#ff5c00;padding:18px 28px;">
          <div style="font-size:20px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">MAD HATS</div>
          <div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>
        </td></tr>
        <tr><td style="padding:40px 28px;text-align:center;">
          <div style="font-size:44px;line-height:1;">&#9989;</div>
          <h1 style="font-size:22px;color:#1a1a2e;margin:18px 0 8px 0;">Quote request received</h1>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:0;">Thanks for confirming your design! One of our MadHats consultants will verify your quote and send it through to you soon.</p>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:12px 0 0 0;">If you left a phone number, we may text or call you when it's ready. You can close this page.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

# Shown on GET /quote/{token} when the customer has ALREADY submitted this quote
# request (lead.quote_confirmed is True) and clicks the email link again — so
# they see "already requested, on its way" instead of the editable form.
QUOTE_ALREADY_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Quote already requested — MadHats</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" height="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;min-height:100vh;">
    <tr><td align="center" style="padding:40px 16px;">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr><td style="background:#ff5c00;padding:18px 28px;">
          <div style="font-size:20px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">MAD HATS</div>
          <div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>
        </td></tr>
        <tr><td style="padding:40px 28px;text-align:center;">
          <div style="font-size:44px;line-height:1;">&#9989;</div>
          <h1 style="font-size:22px;color:#1a1a2e;margin:18px 0 8px 0;">You've already requested this quote</h1>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:0;">We've got your request for this design — one of our MadHats consultants is preparing your quote and will send it through to you soon.</p>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:12px 0 0 0;">No need to submit again. You can close this page.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

QUOTE_ERROR_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Quote link problem — MadHats</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" height="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;min-height:100vh;">
    <tr><td align="center" style="padding:40px 16px;">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr><td style="background:#ff5c00;padding:18px 28px;">
          <div style="font-size:20px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">MAD HATS</div>
          <div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>
        </td></tr>
        <tr><td style="padding:40px 28px;text-align:center;">
          <div style="font-size:44px;line-height:1;">&#9888;&#65039;</div>
          <h1 style="font-size:22px;color:#1a1a2e;margin:18px 0 8px 0;">We couldn't open that quote link</h1>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:0;">{message}</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
