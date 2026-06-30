# Frontend Plan — Ricardo Chatbot Studio (per Figma flow)

**Date:** 2026-07-01
**Decisions:** Replace mock studio with the chatbot flow. Entry = Shopify-widget URL params (`/start?product_id=&variant_id=&colour=&source=`) **plus** a dev product picker for standalone testing. Reuse the existing Tailwind design system (dark base, orange `#FF5C00` accent). No chatbot visual wireframe exists — follow the FigJam flow + existing design language.

## Global constraints
- All backend calls go through one API client that injects `X-Store-Key` (`VITE_STORE_KEY`) and base URL (`VITE_API_BASE_URL`).
- The conversation is **backend-driven**: the frontend renders Ricardo's `reply`, the current `state`, and any `data.options` chips the backend returns; it never decides the next step.
- Backend endpoints: `POST /sessions`, `GET /sessions/{token}`, `POST /chat/{session_id}`, `POST /uploads/logo/{session_id}`, `POST /uploads/pin/{session_id}`, `POST /generate/preview/{session_id}`, `GET /generate/status/{job_id}`, `POST /leads`, `POST /leads/verify/send`, `GET /products?limit=&offset=`.
- Conversation states (from backend `state_machine.py`) drive which input affordance shows.

## Flow (FigJam → states)
Starting point? (customise selected / blank) → greeting → ask_name → ask_purpose → check_youth (→ youth_referral) → ask_quantity → decoration_engine (qty 1 / 2–11 / 12+) → confirm_decoration → ask_has_logo → (upload_logo → ask_remove_bg | describe_design) → ask_placement_zone → ask_placement_position → ask_pin_annotation → (pin_annotate_mode) → generating → ask_email → verify_email → email_verified → send_preview_email → quote_requested → upsell_prompt (max 2) → session_end. Back-track at any step.

## Tasks

### Task 2 — Foundation + entry
- `src/lib/api.ts` (fetch wrapper + all endpoint functions, injects `X-Store-Key`).
- `src/lib/types.ts` (Product, ProductPage, ChatResponse, GenerationStatus, etc.).
- `frontend/.env` + `.env.example` (`VITE_API_BASE_URL=http://localhost:8000`, `VITE_STORE_KEY=mh_pk_madhats_local`).
- App routing: read URL params on load; if `product_id` present → create session (entry_path `pick_first`, store product context) and go to chat; else show dev picker.
- Rebuild `ProductPicker` to fetch `GET /products` (paginated, "Load more") and create a session on select.

### Task 3 — Chatbot conversation
- `src/store/chatStore.ts` (Zustand): session_id, share_token, productRef, messages[], state, options, input mode, loading, error.
- `ChatPanel`: message bubbles (Ricardo/user), option chips from `data.options`, text input + send; on send → `POST /chat`, append reply, update state/options. Starting-point choice at greeting.
- Product context header (cap thumbnail from productRef + name + colour).
- Retire mock studio screens (StudioCanvas/RefineScreen/WornScreen/PreviewPanel) or repurpose.

### Task 4 — Uploads, placement, pin-annotate
- Logo upload affordance when `state == upload_logo` → `POST /uploads/logo`.
- Placement chips already covered by `data.options`.
- Pin-annotate: when `state == ask_pin_annotation`/`pin_annotate_mode`, allow clicking a view to drop a pin (x%,y%) + comment → `POST /uploads/pin`.

### Task 5 — Generation, preview, verification, upsell
- On `data.trigger_generation` (state `generating`) → `POST /generate/preview`, poll `GET /generate/status` → show 4 views / watermarked preview panel.
- Email/phone capture at `ask_email` → `POST /leads` + `POST /leads/verify/send`; await verification → reveal watermarked preview.
- Upsell prompt handling (max 2) and session-end discount mention.

## Notes
- Live chat turns require `ANTHROPIC_API_KEY` in backend `.env` (Haiku). Image gen stays on `stub` until a Gemini key is set.
- Voice input (Web Speech API) and SMS are later (Standard tier) — flow supports text/click first.
