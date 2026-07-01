# Graph Report - .  (2026-06-30)

## Corpus Check
- Corpus is ~26,304 words - fits in a single context window. You may not need a graph.

## Summary
- 88 nodes · 91 edges · 23 communities detected
- Extraction: 70% EXTRACTED · 30% INFERRED · 0% AMBIGUOUS · INFERRED: 27 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Core Frontend & Data Layer|Core Frontend & Data Layer]]
- [[_COMMUNITY_Product Strategy & Design Flows|Product Strategy & Design Flows]]
- [[_COMMUNITY_Conversational AI (Ricardo Bot)|Conversational AI (Ricardo Bot)]]
- [[_COMMUNITY_Chat Interface Logic|Chat Interface Logic]]
- [[_COMMUNITY_Concept Submission & Approval|Concept Submission & Approval]]
- [[_COMMUNITY_Asset Upload & Studio Canvas|Asset Upload & Studio Canvas]]
- [[_COMMUNITY_Modal Interaction|Modal Interaction]]
- [[_COMMUNITY_Product Selection|Product Selection]]
- [[_COMMUNITY_State Store Utils|State Store Utils]]
- [[_COMMUNITY_Watermark Feature|Watermark Feature]]
- [[_COMMUNITY_Upsell Mechanic|Upsell Mechanic]]
- [[_COMMUNITY_Cost & Cache Strategy|Cost & Cache Strategy]]
- [[_COMMUNITY_PostCSS Config|PostCSS Config]]
- [[_COMMUNITY_Tailwind Config|Tailwind Config]]
- [[_COMMUNITY_Vite Config|Vite Config]]
- [[_COMMUNITY_App Entry|App Entry]]
- [[_COMMUNITY_Main Entry|Main Entry]]
- [[_COMMUNITY_RefineScreen Component|RefineScreen Component]]
- [[_COMMUNITY_CapSilhouette Component|CapSilhouette Component]]
- [[_COMMUNITY_WornScreen Component|WornScreen Component]]
- [[_COMMUNITY_Products Data|Products Data]]
- [[_COMMUNITY_Design Tokens|Design Tokens]]
- [[_COMMUNITY_Discount Logic|Discount Logic]]

## God Nodes (most connected - your core abstractions)
1. `Zustand Studio Store` - 14 edges
2. `App Root Component (View Router)` - 8 edges
3. `triggerGenerate Stub Action` - 6 edges
4. `CapSilhouette SVG Renderer` - 6 edges
5. `StudioCanvas Main Workspace Component` - 6 edges
6. `ImageProvider Abstraction (ABC)` - 6 edges
7. `RefineScreen Full-Screen Refine View` - 5 edges
8. `Cap Product Type Definitions (CapStyle, PlacementZone, DecorationStyle, Product)` - 4 edges
9. `ProductPicker Component` - 4 edges
10. `PreviewPanel Component (mockup display + shimmer)` - 4 edges

## Surprising Connections (you probably didn't know these)
- `PRODUCTS Stub Catalogue (6 SKUs)` --semantically_similar_to--> `ProductReference Data Model`  [INFERRED] [semantically similar]
  frontend/src/data/products.ts → CLAUDE.md
- `Zustand Studio Store` --shares_data_with--> `DesignSession Data Model`  [INFERRED]
  frontend/src/store/studioStore.ts → CLAUDE.md
- `triggerGenerate Stub Action` --implements--> `Flow B — Photo-to-Product`  [INFERRED]
  frontend/src/store/studioStore.ts → CLAUDE.md
- `useSpeechInput Custom Hook` --conceptually_related_to--> `Ricardo Conversational Chatbot Flow (PRD v2)`  [INFERRED]
  frontend/src/components/StudioCanvas/index.tsx → docs/superpowers/specs/2026-07-27-madhats-prd-v2.md
- `triggerGenerate Stub Action` --conceptually_related_to--> `ImageProvider Abstraction (ABC)`  [INFERRED]
  frontend/src/store/studioStore.ts → CLAUDE.md

## Hyperedges (group relationships)
- **Frontend View State Machine: store drives component routing** — studiostore_ViewEnum, apptsx_AppComponent, productpicker_ProductPicker, studiocanvas_StudioCanvas, refinescreen_RefineScreen, wornscreen_WornScreen [EXTRACTED 1.00]
- **Stubbed Generation Pipeline (to be replaced by real API)** — studiocanvas_StudioCanvas, studiostore_TriggerGenerate, studiostore_CapStubs, claudemd_ImageProvider [INFERRED 0.85]
- **Web Speech API Voice Input Pattern (reused across components)** — studiocanvas_SpeechInputHook, refinechat_RefineChat, refinescreen_RefineScreen [EXTRACTED 0.95]

## Communities

### Community 0 - "Core Frontend & Data Layer"
Cohesion: 0.18
Nodes (20): App Root Component (View Router), CapSilhouette SVG Renderer, DesignSession Data Model, ProductReference Data Model, React DOM Entry Point, PreviewPanel Component (mockup display + shimmer), ProductPicker Component, PRODUCTS Stub Catalogue (6 SKUs) (+12 more)

### Community 1 - "Product Strategy & Design Flows"
Cohesion: 0.18
Nodes (12): Input Moderation Service (moderation.py), Business Goals (browsers to buyers, reduce manual quoting), Two-Tier Image Strategy (fast preview + high-fidelity final), Flow A — Describe It, See It, Flow B — Photo-to-Product, Flow C — Worn / In-Context, Hard Constraints (Never Violate), ImageProvider Abstraction (ABC) (+4 more)

### Community 2 - "Conversational AI (Ricardo Bot)"
Cohesion: 0.22
Nodes (9): Claude Haiku LLM (Intent Extraction), Conversation Orchestrator (orchestrator.py), prompts.py — Single Source of Truth for Prompt Strings, Ricardo Chatbot Persona, ConversationState Enum & Transition Table, Ricardo Conversational Chatbot Flow (PRD v2), Decoration Recommendation Engine, Client Vision: Conversational AI Replaces Form-Based UX (+1 more)

### Community 3 - "Chat Interface Logic"
Cohesion: 0.33
Nodes (3): handleKey(), handleSend(), if()

### Community 4 - "Concept Submission & Approval"
Cohesion: 0.29
Nodes (7): Email Service via Resend (email.py), ApprovalSubmission Data Model, Human-in-the-Loop Requirement, ConceptModal Concept Submission Form, Email Verification Sub-Flow, Lead Data Model (name, email, phone, verified), Client Rationale for Delayed Lead Capture (after design, not upfront)

### Community 5 - "Asset Upload & Studio Canvas"
Cohesion: 0.33
Nodes (0): 

### Community 6 - "Modal Interaction"
Cohesion: 0.67
Nodes (0): 

### Community 7 - "Product Selection"
Cohesion: 0.67
Nodes (0): 

### Community 8 - "State Store Utils"
Cohesion: 0.67
Nodes (0): 

### Community 9 - "Watermark Feature"
Cohesion: 1.0
Nodes (3): Watermark Service (watermark.py), Watermarked Design Delivery Feature, Client Watermark Requirement (prevent reuse without ordering)

### Community 10 - "Upsell Mechanic"
Cohesion: 1.0
Nodes (2): Post-Design Upsell Prompts (max 2 per session), Client Upsell Vision (add logo zones, discount prompts)

### Community 11 - "Cost & Cache Strategy"
Cohesion: 1.0
Nodes (2): Generation Cache (keyed by product+colour+prompt+asset hash), Cost Controls Rationale (preview cheap, finals 2K, cache, rate-limit)

### Community 12 - "PostCSS Config"
Cohesion: 1.0
Nodes (0): 

### Community 13 - "Tailwind Config"
Cohesion: 1.0
Nodes (0): 

### Community 14 - "Vite Config"
Cohesion: 1.0
Nodes (0): 

### Community 15 - "App Entry"
Cohesion: 1.0
Nodes (0): 

### Community 16 - "Main Entry"
Cohesion: 1.0
Nodes (0): 

### Community 17 - "RefineScreen Component"
Cohesion: 1.0
Nodes (0): 

### Community 18 - "CapSilhouette Component"
Cohesion: 1.0
Nodes (0): 

### Community 19 - "WornScreen Component"
Cohesion: 1.0
Nodes (0): 

### Community 20 - "Products Data"
Cohesion: 1.0
Nodes (0): 

### Community 21 - "Design Tokens"
Cohesion: 1.0
Nodes (1): Tailwind Custom Design Tokens (colors, fonts)

### Community 22 - "Discount Logic"
Cohesion: 1.0
Nodes (1): Conditional Discount Messaging (qty + day-of-week)

## Knowledge Gaps
- **23 isolated node(s):** `React DOM Entry Point`, `View State Enum (picker|studio|refine|worn)`, `CapViewGrid 4-Angle Image Grid`, `Tailwind Custom Design Tokens (colors, fonts)`, `PromptBuilder Service` (+18 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Upsell Mechanic`** (2 nodes): `Post-Design Upsell Prompts (max 2 per session)`, `Client Upsell Vision (add logo zones, discount prompts)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cost & Cache Strategy`** (2 nodes): `Generation Cache (keyed by product+colour+prompt+asset hash)`, `Cost Controls Rationale (preview cheap, finals 2K, cache, rate-limit)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `PostCSS Config`** (1 nodes): `postcss.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Tailwind Config`** (1 nodes): `tailwind.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Vite Config`** (1 nodes): `vite.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `App Entry`** (1 nodes): `App.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Main Entry`** (1 nodes): `main.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `RefineScreen Component`** (1 nodes): `index.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `CapSilhouette Component`** (1 nodes): `CapSilhouette.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `WornScreen Component`** (1 nodes): `index.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Products Data`** (1 nodes): `products.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Design Tokens`** (1 nodes): `Tailwind Custom Design Tokens (colors, fonts)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Discount Logic`** (1 nodes): `Conditional Discount Messaging (qty + day-of-week)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Zustand Studio Store` connect `Core Frontend & Data Layer` to `Product Strategy & Design Flows`, `Concept Submission & Approval`?**
  _High betweenness centrality (0.166) - this node is a cross-community bridge._
- **Why does `triggerGenerate Stub Action` connect `Product Strategy & Design Flows` to `Core Frontend & Data Layer`?**
  _High betweenness centrality (0.118) - this node is a cross-community bridge._
- **Why does `ImageProvider Abstraction (ABC)` connect `Product Strategy & Design Flows` to `Conversational AI (Ricardo Bot)`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `triggerGenerate Stub Action` (e.g. with `ImageProvider Abstraction (ABC)` and `Flow A — Describe It, See It`) actually correct?**
  _`triggerGenerate Stub Action` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `React DOM Entry Point`, `View State Enum (picker|studio|refine|worn)`, `CapViewGrid 4-Angle Image Grid` to the rest of the system?**
  _23 weakly-connected nodes found - possible documentation gaps or missing edges._