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
- Use Australian-friendly, professional but casual language.

Hard rules:
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
    "ask_placement_zone": "Ask where they'd like the design placed: front panel, side, back, "
    "or under the brim.",
    "ask_placement_position": "Ask for the precise position within the {placement_zone} "
    "(left, centre or right; upper, middle or lower).",
    "ask_pin_annotation": "Ask if they'd like to drop a pin on the cap to add a specific note "
    "about placement, or skip and generate now.",
    "pin_annotate_mode": "Acknowledge the pin note and ask if they want to add another or finish.",
    "generating": "Tell them you're putting the design together now, and while it renders ask "
    "for their email so you can send it across when ready.",
    "ask_email": "Politely ask for their email so you can send the finished design.",
    "verify_email": "Let them know you've sent a quick verification email and ask them to click "
    "the link to confirm. Mention to check spam.",
    "email_verified": "Thank them for confirming their email.",
    "send_preview_email": "Let them know their design is ready and on its way to their inbox.",
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

REPLY_GENERATION_PROMPT = """Current step instruction: {state_instruction}

Known details so far (JSON): {collected}

Write Ricardo's next message to the customer. Follow the step instruction exactly,
stay in persona, keep it to 1-3 short sentences. Do not ask anything beyond this step.
Return ONLY the message text, no quotes or labels.
"""

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
    "generating": (
        "I'm putting your design together now! "
        "While that renders, what's your email so I can send it across when it's ready?"
    ),
    "ask_email": "What's the best email address to send your design to?",
    "verify_email": (
        "I've sent a quick verification to your inbox — just click the link to confirm. "
        "Check your spam folder if you don't see it!"
    ),
    "email_verified": "Email confirmed, thanks!",
    "send_preview_email": "Your design is on its way to your inbox now.",
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

IMAGE_GEN_BASE_TEMPLATE = """Composite the supplied design onto the REAL product reference
photo provided as the first image. Do not redraw, reshape, or regenerate the cap itself —
preserve its exact shape, colour, fabric, seams, and lighting from the reference photo.

Cap style: {style}
Cap colour: {colour}
Design intent: {design_summary}
"""

PLACEMENT_CONTEXT_TEMPLATE = """Placement: apply the design on the {placement_zone} of the cap,
positioned at {placement_position}. Keep the design proportional and aligned to the panel's
natural curvature and perspective."""

EMBROIDERY_STYLE_MODIFIER = """Render the design as realistic stitched EMBROIDERY: visible
thread texture, slight raised relief, satin-stitch edges, matte thread sheen. No flat print look."""

PRINT_STYLE_MODIFIER = """Render the design as a flat screen-PRINT / heat-transfer: smooth,
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

PREVIEW_EMAIL_SUBJECT = "Your MadHats design preview is ready"

PREVIEW_EMAIL_BODY = """Hi {name},

Here's the preview of your custom cap design:

{image_url}

This is a watermarked preview for review only. One of our team will be in touch shortly
with your quote.

— Ricardo, MadHats AI Design Studio
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

Design image (internal, clean): {image_url}

Please prepare and send the quote directly to the customer.
"""
