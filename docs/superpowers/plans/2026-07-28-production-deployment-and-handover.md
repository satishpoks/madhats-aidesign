# Production Deployment & Client Handover — Master Checklist

**Project:** MadHats AI Design Studio
**Document owner:** Satish Pokhrel
**Date:** 2026-07-28
**Status:** Living document — tick items as they complete, record dates and owners inline.

---

## How to use this document

This is a **two-part runbook**:

- **Part A — Deployment (§1–§9):** everything needed to get the system live and
  serving real customers on a production domain. Runs top to bottom; later
  phases depend on earlier ones.
- **Part B — Handover (§10–§14):** transferring ownership, access, knowledge,
  and ongoing responsibility to the client.

**Do not start Part B until Part A is signed off.** Handing over a system that
isn't verified live means the client inherits your debugging.

Each item has a checkbox, an owner column, and — where it matters — the exact
command or the failure symptom you'll see if you skip it.

**Legend:**
🔴 = blocking (system will not work without it) · 🟡 = required before go-live ·
🟢 = post-launch / can follow

---

# PART A — DEPLOYMENT

---

## §1. Pre-flight — accounts, access, and decisions

Nothing here touches a server. This is the inventory of what must exist and who
owns it. **Fill this table in before touching anything else** — half of all
deployment delays are "waiting for someone to grant access".

### 1.1 Accounts required 🔴

| # | Account / service | Purpose | Who owns it at go-live | Who owns it after handover | Status |
|---|---|---|---|---|---|
| 1.1.1 | **GitHub** (repo) | Source of truth for code | You | Client org | ☐ |
| 1.1.2 | **Domain registrar** | `getaiconsult.com.au` / client domain | | | ☐ |
| 1.1.3 | **DNS provider** | A records for api + frontend | | | ☐ |
| 1.1.4 | **Server / VPS host** | Runs the Docker stack | | | ☐ |
| 1.1.5 | **Supabase** | Postgres 17 + private object storage | | | ☐ |
| 1.1.6 | **Anthropic Console** | Claude Haiku (conversation LLM) | | | ☐ |
| 1.1.7 | **Google AI Studio / GCP** | Gemini image generation | | | ☐ |
| 1.1.8 | **Resend** | Transactional email | | | ☐ |
| 1.1.9 | **Sentry** (optional) | Error tracking | | | ☐ |
| 1.1.10 | **Shopify admin** | Storefront button install | Client | Client | ☐ |

> ⚠️ **Every one of 1.1.5–1.1.9 is a billed service.** Decide *now* whether they
> are created under the client's billing identity from day one, or under yours
> and transferred later. **Creating them under the client's billing from the
> start avoids a painful migration** — API keys generally cannot be moved
> between accounts, so a later transfer means re-issuing keys and redeploying.

### 1.2 Decisions to confirm with the client 🔴

| # | Decision | Default / recommendation | Confirmed |
|---|---|---|---|
| 1.2.1 | Production hostnames | `madhats.getaiconsult.com.au` (studio) + `api.madhats.getaiconsult.com.au` (backend) | ☐ |
| 1.2.2 | Sending email address | `studio@madhats.com.au` — **must be on a domain the client controls DNS for** (see §4.4) | ☐ |
| 1.2.3 | Sales notification inbox | `sales@madhats.com.au` — receives every quote request | ☐ |
| 1.2.4 | Canvas orchestrator version | `CANVAS_ORCHESTRATOR_V2` — decide **on** (step-by-step v2) or **off** (v1) and **do not flip after launch** (see §5.3) | ☐ |
| 1.2.5 | AI spend caps | `REGEN_EDITS_PER_SESSION=3`, `DESIGNS_PER_CUSTOMER_PER_DAY=2` | ☐ |
| 1.2.6 | CORS policy | Currently open (`*`). Lock to the storefront + studio origins? | ☐ |
| 1.2.7 | Asset/image retention policy | Open decision from CLAUDE.md §12 — how long generated images are kept | ☐ |
| 1.2.8 | Who is on-call for the box | Client IT / you / third party | ☐ |
| 1.2.9 | Support window after handover | Recommend 30 days bug-fix + 30 days advisory | ☐ |

### 1.3 Pre-flight verification 🟡

- ☐ **1.3.1** Full test suite green on the branch being deployed:
  ```bash
  cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q
  cd frontend && npx vitest run src/__tests__
  ```
  Record the numbers here: backend `____ passed` / frontend `____ passed, ____ failed`.
  > Known-acceptable at time of writing: backend 1057 passing; frontend 249
  > passing / 2 failing (the 2 are pre-existing `adminQuotes` failures — missing
  > Router context, not a regression).
- ☐ **1.3.2** Frontend production build succeeds locally: `cd frontend && npm run build`
- ☐ **1.3.3** Prod Caddyfile validates:
  ```bash
  MSYS_NO_PATHCONV=1 docker run --rm \
    -v "$PWD/caddy/Caddyfile.prod:/etc/caddy/Caddyfile:ro" \
    caddy:2.8-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
  ```
  > Expect the warning `server is listening only on the HTTP port, so no
  > automatic HTTPS will be applied` — that is CORRECT as of 2026-07-29. The
  > box's nginx terminates TLS; Caddy is a plain-HTTP hostname router behind it.
  > `-e ACME_EMAIL=…` is no longer needed (the `email` directive is gone).
- ☐ **1.3.3b** nginx vhost installed and TLS issued on the box — see
  `nginx/madhats.conf.example` and CLAUDE.md §13c ("nginx side"):
  `sudo nginx -t && sudo systemctl reload nginx`, then
  `sudo certbot --nginx --redirect -d … -d …`.
  Confirm BOTH hostnames resolve to the box first (Let's Encrypt: 5 duplicate
  certs/week). certbot rewrites the site file: end state is `http://` → 301 →
  `https://`, `https://` serves. Pre-certbot, only HTTP answers and it is a
  connectivity test only — assets/API still target HTTPS, so use `curl -sI`.
- ☐ **1.3.4** Branch merged to `master` (or the agreed release branch) and tagged, e.g. `git tag v1.0.0-prod && git push --tags`

---

## §2. Source control

- ☐ **2.1** 🔴 Repo exists on GitHub with full history pushed (`git push --all && git push --tags`)
- ☐ **2.2** 🔴 `master` is the release branch; branch-protection rule requires PR review (optional but recommended)
- ☐ **2.3** 🔴 Confirm **no secrets are committed**:
  ```bash
  git log --all --full-history -- .env
  git grep -nEi "sk-ant-|AIza|re_[A-Za-z0-9]{20}|service_role" $(git rev-list --all) 2>/dev/null | head
  ```
  If anything surfaces, **rotate that key immediately** — history rewriting is not enough once it's been pushed.
- ☐ **2.4** 🟡 `.gitignore` covers `.env*`, `.claude/worktrees/`, `frontend/dist`, `node_modules`
- ☐ **2.5** 🟡 `README.md` and `CLAUDE.md` reflect the final architecture (CLAUDE.md is the single source of truth for agents and future devs — it is a **handover asset**, not internal scratch)
- ☐ **2.6** 🟡 Add a deploy key or machine user for the server, **not** a personal PAT:
  ```bash
  # on the server
  ssh-keygen -t ed25519 -C "madhats-prod-deploy" -f ~/.ssh/id_ed25519_deploy
  # add the .pub as a read-only Deploy Key in GitHub → Settings → Deploy keys
  ```
- ☐ **2.7** 🔴 Clone onto the server and verify `git fetch && git pull` works non-interactively

---

## §3. Server provisioning

> Prod runs on a **self-hosted Docker box**, not Railway. The box's own
> **nginx** owns `:80`/`:443` and terminates TLS (changed 2026-07-29 — those
> ports were already in use, so Caddy could not bind them or run ACME). nginx
> proxies both hostnames to Caddy on `127.0.0.1:8480`; Caddy is the only
> *container* publishing ports, and now only routes by hostname.
>
> **This topology is live-verified on the STAGING box (2026-07-29)** —
> `mhstaging.getaiconsult.com.au` / `api.mhstaging.getaiconsult.com.au`, certs
> issued by certbot, full chain working. Production (`madhats.*`) is the same
> stack with different `STUDIO_HOST`/`API_HOST` values, so the checklist below
> applies to both; where it says a hostname, substitute the environment's.

### 3.1 Machine 🔴

- ☐ **3.1.1** VPS provisioned. **Minimum: 2 vCPU / 4 GB RAM / 40 GB SSD.** (Image
  generation is offloaded to Gemini, but Pillow compositing, the Node static
  build, and Docker layers all need headroom. A 1 GB box will OOM during
  `npm run build`.)
- ☐ **3.1.2** OS: Ubuntu 22.04 LTS or 24.04 LTS
- ☐ **3.1.3** Static public IPv4 assigned and recorded: `________________`
- ☐ **3.1.4** Non-root sudo user created; root SSH login disabled; key-only auth
- ☐ **3.1.5** Timezone + NTP set (`timedatectl set-timezone Australia/Sydney`) — token TTLs and cert renewal depend on correct clock
- ☐ **3.1.6** Swap file configured (2 GB) if RAM ≤ 4 GB

### 3.2 Firewall 🔴

- ☐ **3.2.1** Allow only: `22` (SSH), `80` (ACME + redirect), `443` (HTTPS)
  ```bash
  sudo ufw default deny incoming && sudo ufw default allow outgoing
  sudo ufw allow 22 && sudo ufw allow 80 && sudo ufw allow 443
  sudo ufw enable && sudo ufw status verbose
  ```
  > 80/443 are **nginx's** (it terminates TLS). Do **not** open `8480` — Caddy
  > binds it on `127.0.0.1` only, and it carries the site in cleartext.
- ☐ **3.2.2** ⚠️ **Ports 8000 and 5173 are published by the prod Caddy for
  *legacy redirects only*.** If you open them at the firewall, do so knowingly
  and temporarily (§9.5). They serve 301s to the HTTPS hosts so
  already-delivered email links don't dead-end.
- ☐ **3.2.3** 🔴 **Never add a `ports:` mapping to the `backend` service.** It
  runs with `TRUSTED_PROXY_HOSTS: "*"`, which is safe *only* because nothing
  off the compose network can reach it. Exposing it turns that line into a
  rate-limit bypass (any caller rotates `X-Forwarded-For` for a fresh bucket)
  **and** serves the API in cleartext.

### 3.3 Docker 🔴

- ☐ **3.3.1** Install Docker Engine + Compose plugin (official repo, not the distro snap):
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER   # log out/in
  docker compose version          # must print v2.x
  ```
- ☐ **3.3.2** `docker` daemon enabled at boot: `sudo systemctl enable --now docker`
- ☐ **3.3.3** Log rotation configured so containers don't fill the disk — `/etc/docker/daemon.json`:
  ```json
  { "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
  ```
  then `sudo systemctl restart docker`
- ☐ **3.3.4** Weekly `docker image prune -af --filter "until=168h"` cron (image rebuilds accumulate fast)

### 3.4 Hardening 🟢

- ☐ **3.4.1** `unattended-upgrades` enabled for security patches
- ☐ **3.4.2** `fail2ban` on SSH
- ☐ **3.4.3** Disk-space alert at 80% (a full disk silently breaks cert renewal *and* image uploads)

---

## §4. DNS & third-party services

> Do DNS **before** running certbot. Retrying ACME against Let's Encrypt while
> DNS is unresolved is the fastest way to burn the **duplicate-certificate rate
> limit (5/week)** and lock yourself out of issuance for the real domain. (As of
> 2026-07-29 the ACME client is **certbot on the host nginx**, not Caddy — the
> risk moved, it did not go away.)

### 4.1 Subdomain records 🔴

- ☐ **4.1.1** `A` record: `madhats` → server IP (studio frontend)
- ☐ **4.1.2** `A` record: `api.madhats` → server IP (backend)
- ☐ **4.1.3** TTL set low (300s) during cutover; raise afterwards
- ☐ **4.1.4** **Verify propagation before deploying**:
  ```bash
  dig +short madhats.getaiconsult.com.au
  dig +short api.madhats.getaiconsult.com.au
  ```
  Both must return the server IP. **Do not proceed until they do.**
- ☐ **4.1.5** If behind Cloudflare: set the records to **DNS-only (grey cloud)**
  for initial issuance. Orange-cloud proxying intercepts the ACME HTTP-01
  challenge and certbot will never get a cert.

### 4.2 Supabase 🔴

- ☐ **4.2.1** Hosted Supabase project created (region: closest to AU — `ap-southeast-2`)
- ☐ **4.2.2** Record `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
  > The service-role key bypasses RLS entirely. It lives **only** in the
  > server's `.env` — never in the frontend bundle, never in the repo.
- ☐ **4.2.3** 🔴 **Create the private storage bucket** named exactly
  `madhats-assets` (matching `SUPABASE_STORAGE_BUCKET`). **Public access OFF.**
  Every customer-facing asset URL is signed with `SIGNED_URL_TTL` or proxied
  through `/media`; a public bucket breaks the security model.
  *Symptom if missing:* every upload 404s and no product photo, logo, or
  generated preview ever renders.
- ☐ **4.2.4** 🔴 **Apply all 17 SQL migrations** from `backend/supabase/migrations/`
  in filename order. Either link the CLI (`npx supabase link --project-ref <ref>
  && npx supabase db push`) or paste each file into the SQL editor in order.
- ☐ **4.2.5** 🔴 **Verify the migrations actually landed** — this has bitten this
  project before (two 2026-07-24 migrations sat unapplied and would have
  PostgREST-errored every generation-completion write). Spot-check the newest
  columns:
  ```sql
  select column_name from information_schema.columns
   where table_name='leads' and column_name like '%reference%';       -- expect reference_code
  select column_name from information_schema.columns
   where table_name='generations' and column_name='render_notes';     -- expect 1 row
  select to_regclass('public.admin_users');                           -- expect admin_users
  ```
  A missing column shows up as PostgREST error `42703` at runtime, not at deploy.
- ☐ **4.2.6** 🟡 Decide seed strategy: `seed.sql` creates the default `madhats`
  store with key `mh_pk_madhats_local`. For production **either** run it **or**
  create the store via `POST /admin/stores` (§7.1). Do not do both.
- ☐ **4.2.7** 🟡 Enable **Point-in-Time Recovery / daily backups** on the Supabase project
- ☐ **4.2.8** 🟡 Note the plan tier and its connection/row limits; set a spend alert

### 4.3 AI provider keys 🔴

- ☐ **4.3.1** **Anthropic** — create an API key for Claude Haiku (`CLAUDE_HAIKU_MODEL=claude-haiku-4-5-20251001`)
- ☐ **4.3.2** **Anthropic** — set a monthly spend limit + usage alert in the Console
  > ⚠️ Without a key the conversation still runs (canned replies + heuristics),
  > **but the v2 canvas flow degrades to a tap-through wizard** and the
  > describe-a-change refine path **permanently stalls**. Treat the key as required.
- ☐ **4.3.3** **Google** — create a Gemini API key with **billing enabled**
  (`GEMINI_API_KEY`)
- ☐ **4.3.4** **Google** — verify the two image-output models are available to
  *this* key via ListModels: `gemini-2.5-flash-image` (preview) and
  `gemini-3-pro-image` (final). Model IDs are env-driven and must never be
  hardcoded.
- ☐ **4.3.5** **Google** — request/confirm image-generation **quota** is high
  enough for expected volume. Quota 429s are the single most common production
  failure here; they're retried and ops-alerted, but sustained 429s mean no
  customer gets a design.
- ☐ **4.3.6** **Google** — set a budget alert on the GCP billing account

### 4.4 Resend (transactional email) 🔴

> The DNS work here is the real task — "add DNS record" in the original list is
> mostly this. Skipping it means every customer email lands in spam or is
> rejected, which silently kills the whole funnel (verification is a **hard
> gate** — an unverified customer cannot finish).

- ☐ **4.4.1** Resend account created; API key issued (`RESEND_API_KEY`)
- ☐ **4.4.2** 🔴 **Domain added and verified** in Resend for the sending domain
  (e.g. `madhats.com.au`). Requires DNS records **on the sending domain**, which
  may be controlled by the client, not you — start this early, it's the most
  common blocker.
- ☐ **4.4.3** 🔴 Add the Resend-provided **DKIM** `TXT`/`CNAME` records
- ☐ **4.4.4** 🔴 Add / merge the **SPF** record (`v=spf1 include:...`) — note you
  can only have **one** SPF record; merge with any existing one rather than adding a second
- ☐ **4.4.5** 🟡 Add a **DMARC** record (`_dmarc`), start at `p=none`
- ☐ **4.4.6** 🔴 Confirm the domain shows **Verified** in Resend before go-live
- ☐ **4.4.7** 🔴 `RESEND_FROM_ADDRESS` is on the verified domain
- ☐ **4.4.8** 🔴 ⚠️ **Move off the Resend sandbox.** In sandbox mode Resend only
  delivers to the account owner's address and **403s `+alias` addresses** —
  which is exactly what makes verification testing look broken.
- ☐ **4.4.9** 🟡 Send a real test email to a Gmail + an Outlook address; confirm
  inbox placement (not spam) and that the inlined CID logo/preview renders

### 4.5 Sentry 🟢

- ☐ **4.5.1** Project created; `SENTRY_DSN` recorded
- ☐ **4.5.2** Alert rules routed to a monitored inbox/Slack
- ☐ **4.5.3** 🔴 Confirm **no PII in events** — customer name/email must never
  reach logs or breadcrumbs (hard constraint, CLAUDE.md §8.10)

---

## §5. Environment configuration

> 🔴 **The single most dangerous item in this entire document is
> `VITE_API_BASE_URL`.** Vite **inlines every `VITE_*` var into the JS bundle at
> build time**. A hosted frontend never reads a runtime `.env`. If it's wrong
> when the image is built, the browser calls `http://localhost:8000` (or a stale
> dev IP) and the site is a total outage that *presents as a backend fault*.
> **After changing it you must `--build`, not just recreate.**

### 5.1 Create the server `.env` 🔴

- ☐ **5.1.1** `cp .env.example .env` on the server; `chmod 600 .env`
- ☐ **5.1.2** Confirm `.env` is git-ignored and excluded from images (`frontend/.dockerignore`)

### 5.2 Fill in production values 🔴

| Var | Production value | ☐ |
|---|---|---|
| `SUPABASE_URL` | hosted project URL | ☐ |
| `SUPABASE_ANON_KEY` | from Supabase | ☐ |
| `SUPABASE_SERVICE_ROLE_KEY` | from Supabase — **secret** | ☐ |
| `SUPABASE_STORAGE_BUCKET` | `madhats-assets` | ☐ |
| `VITE_API_BASE_URL` | `https://api.madhats.getaiconsult.com.au` — **compiled in** | ☐ |
| `VITE_STORE_KEY` | the store's **publishable** key (§7.1) | ☐ |
| `EMAIL_VERIFY_BASE_URL` | `https://api.madhats.getaiconsult.com.au` | ☐ |
| `STUDIO_BASE_URL` | `https://madhats.getaiconsult.com.au` | ☐ |
| `ANTHROPIC_API_KEY` | | ☐ |
| `CLAUDE_HAIKU_MODEL` | `claude-haiku-4-5-20251001` | ☐ |
| `GEMINI_API_KEY` | | ☐ |
| `IMAGE_PROVIDER_PREVIEW` | 🔴 `gemini_flash` — **not `stub`** | ☐ |
| `IMAGE_PROVIDER_FINAL` | 🔴 `gemini_pro` — **not `stub`** | ☐ |
| `GEMINI_PREVIEW_MODEL` | `gemini-2.5-flash-image` | ☐ |
| `GEMINI_FINAL_MODEL` | `gemini-3-pro-image` | ☐ |
| `RESEND_API_KEY` | | ☐ |
| `RESEND_FROM_ADDRESS` | on the verified domain | ☐ |
| `SALES_NOTIFICATION_EMAIL` | client's sales inbox | ☐ |
| `ADMIN_SECRET` | 🔴 **generate fresh** — never `change-me-in-production` | ☐ |
| `ADMIN_JWT_SECRET` | 🔴 generate fresh (defaults to `ADMIN_SECRET` if blank) | ☐ |
| `RATE_LIMIT_RPM` | `10` (tune after observing traffic) | ☐ |
| `SIGNED_URL_TTL` | `3600` | ☐ |
| `ALLOWED_ORIGINS` | `*` today; see 5.4 | ☐ |
| `VERIFICATION_TOKEN_TTL_SECONDS` | `900` | ☐ |
| `QUOTE_TOKEN_TTL_SECONDS` | `2592000` (30d) | ☐ |
| `REGEN_EDITS_PER_SESSION` | `3` | ☐ |
| `DESIGNS_PER_CUSTOMER_PER_DAY` | `2` | ☐ |
| `APP_ENV` | `production` | ☐ |
| `SENTRY_DSN` | | ☐ |
| `CHATBOT_PERSONA_NAME` | `Ricardo` | ☐ |
| `CANVAS_ORCHESTRATOR_V2` | per decision 1.2.4 | ☐ |
| `ACME_EMAIL` | ⚪ **no longer used** (2026-07-29) — nginx holds the certs; blank is harmless | ☐ |
| `STUDIO_HOST` | 🔴 **required** — hostname Caddy routes on; must equal the nginx `server_name` exactly | ☐ |
| `API_HOST` | 🔴 **required** — ditto for the backend host. Mismatch = blank pages, not an error | ☐ |
| `TRUSTED_PROXY_HOSTS` | 🔴 **leave BLANK** — compose sets it itself, next to the port mapping that justifies it | ☐ |
| `TLS_PROXY_HOST` | unused in prod (static build, no HMR) | ☐ |

Generate secrets with:
```bash
openssl rand -hex 32
```

### 5.3 The orchestrator flag 🔴

- ☐ **5.3.1** Set `CANVAS_ORCHESTRATOR_V2` to the agreed value **before first
  customer traffic**.
  > ⚠️ **Flipping it later strands in-flight v1 canvas sessions** parked at
  > `canvas_design` — v2 never reaches the state v1's outro expects, so those
  > customers cannot finish. If you must flip it, do so during a traffic lull
  > and accept that open sessions are lost.

### 5.4 CORS 🟡

- ☐ **5.4.1** `ALLOWED_ORIGINS` currently defaults to `*`, which
  `main.py:build_cors_kwargs` serves via `allow_origin_regex=".*"` (reflecting
  the request Origin — a literal `*` is illegal alongside `allow_credentials`).
- ☐ **5.4.2** Decide whether to lock it to a comma-separated list. If you do, it
  **must** include the studio origin and the Shopify storefront origin, or the
  page loads and every request fails.
  > Per-store CORS is a **known gap** — the setting is global across all tenants.

---

## §6. Deploy

### 6.1 First deploy 🔴

- ☐ **6.1.1** DNS verified resolving (§4.1.4) — **do not skip**
- ☐ **6.1.2** `.env` complete (§5)
- ☐ **6.1.3** Deploy:
  ```bash
  cd ~/madhats-aidesign
  git pull
  docker compose -f docker-compose.prod.yml down
  docker compose -f docker-compose.prod.yml up -d --build
  ```
  > 🔴 **The `-f` is not optional.** A bare `docker compose down` loads the
  > **dev** compose file, misses the prod project's containers entirely, and
  > leaves them running. The dev stack is **not a supported way to serve
  > production**: it binds `:80`/`:443` too (colliding or squatting), serves only
  > `localhost`/`api.localhost` under Caddy's *internal* CA that no customer
  > browser trusts, and defaults `VITE_API_BASE_URL` to `https://api.localhost`.
- ☐ **6.1.4** All five services up: `docker compose -f docker-compose.prod.yml ps`
  → `backend`, `frontend`, `caddy`, `watchdog` all `running`
- ☐ **6.1.5** `docker compose -f docker-compose.prod.yml logs --tail=100` shows no startup errors

### 6.2 Verify the bundle 🔴

- ☐ **6.2.1** Confirm the **right API URL was actually baked in** — the `:?`
  guard in compose catches an *unset* value, but a **stale** one builds happily:
  ```bash
  docker compose -f docker-compose.prod.yml exec frontend \
    sh -c "grep -o 'https://api\.[a-z0-9.-]*' /app/dist/assets/*.js | head"
  ```
  Must print the production API host. If it prints `localhost` or an old IP:
  fix `.env`, then `docker compose -f docker-compose.prod.yml up -d --build frontend`.

### 6.3 Smoke the services 🔴

- ☐ **6.3.1** `curl -s https://api.madhats.getaiconsult.com.au/health` → `{"status":"ok"}`
- ☐ **6.3.2** `curl -sI https://madhats.getaiconsult.com.au` → `200`
- ☐ **6.3.3** Studio loads in a real browser with **no console errors**
- ☐ **6.3.4** `GET /products` with `X-Store-Key` returns the catalogue

---

## §7. TLS / SSL

**As of 2026-07-29 TLS lives in the host nginx, not Caddy** (nginx already owned
`:80`/`:443`). certbot obtains and renews; Caddy issues nothing.

- ☐ **7.1** 🔴 Both hosts serve valid certs:
  ```bash
  curl -vI https://madhats.getaiconsult.com.au 2>&1 | grep -Ei "issuer|expire|subject"
  curl -vI https://api.madhats.getaiconsult.com.au 2>&1 | grep -Ei "issuer|expire|subject"
  ```
- ☐ **7.2** 🔴 certbot holds both names and auto-renewal is armed:
  ```bash
  sudo certbot certificates                  # both hostnames listed, not expired
  sudo systemctl status certbot.timer        # active
  sudo certbot renew --dry-run               # renewal actually works
  ```
  > `caddy_data` is **no longer** where certs live — it is retained for Caddy's
  > own state only, and pruning it no longer risks the Let's Encrypt limit.
- ☐ **7.2b** 🔴 The nginx→Caddy hop works and Caddy routes by hostname:
  ```bash
  curl -sI -H 'Host: madhats.getaiconsult.com.au'     http://127.0.0.1:8480/
  curl -sI -H 'Host: api.madhats.getaiconsult.com.au' http://127.0.0.1:8480/health
  ```
  > An EMPTY 200 here (not a 404 — verified) means Caddy has no site block for
  > that Host: either nginx isn't sending `proxy_set_header Host $host`, or
  > `STUDIO_HOST`/`API_HOST` don't match the nginx `server_name`.
- ☐ **7.2c** 🔴 Caddy's plain-HTTP port is **loopback-only** — `docker compose -f
  docker-compose.prod.yml ps` must show `127.0.0.1:8480->80/tcp`, never
  `0.0.0.0:8480`. A public bind exposes the whole site in cleartext AND makes
  `TRUSTED_PROXY_HOSTS: "*"` a rate-limit bypass.
- ☐ **7.3** 🟡 `http://` redirects to `https://` on both hosts
- ☐ **7.4** 🟡 No mixed-content warnings anywhere in the studio
- ☐ **7.5** 🔴 **`TRUSTED_PROXY_HOSTS` is reaching the backend:**
  ```bash
  docker compose -f docker-compose.prod.yml exec backend env | grep TRUSTED
  ```
  Must be `*`. Two failures if not:
  1. `app/storage.py:media_url` builds **every** private-asset URL from
     `request.base_url` (~16 call sites — brand logo, hat-type angles, company
     graphics, blank-hat composites, session `view_images`, admin thumbnails,
     quote components). Untrusted → Caddy's plain-HTTP hop wins, all come back
     `http://`, the browser blocks them, **and the studio renders with no
     imagery at all**.
  2. Quieter but worse under load: client IP is recovered from
     `X-Forwarded-For`. Untrusted → `request.client.host` is Caddy's container
     IP, so **every customer shares one rate-limit bucket** and everyone gets 429s.
- ☐ **7.6** 🟢 Renewal watch: check logs ~60 days in, or add an external cert-expiry monitor
- ☐ **7.7** 🟢 Optional external grade check (SSL Labs) → A or better

---

## §8. Store onboarding & application configuration

The system is **multi-tenant**. A running stack with no configured store serves
nothing.

### 8.1 Create the store 🔴

- ☐ **8.1.1** `POST /admin/stores` with `X-Admin-Secret` → auto-generates the
  `public_key` (`mh_pk_...`). Record it: `________________`
- ☐ **8.1.2** 🔴 Put that key in `.env` as `VITE_STORE_KEY` and **rebuild the
  frontend** (it's compiled in):
  `docker compose -f docker-compose.prod.yml up -d --build frontend`
- ☐ **8.1.3** Set the store's `shopify_domain`, `allowed_origins`, `sales_notification_email`, persona name/greeting
- ☐ **8.1.4** 🔴 `POST /admin/stores/{id}/sync` — pulls the store's `products.json`
  into `product_references`
- ☐ **8.1.5** Verify: `GET /products` with the store key returns real products
  > ⚠️ **Known gap:** `/products` returns PostgREST's default **1000-row cap**.
  > A larger catalogue needs pagination before launch.

### 8.2 Product image quality 🔴

- ☐ **8.2.1** ⚠️ **Canvas-enabled products must carry real per-angle photos.**
  A synced product with only a front image has `_map_views` alias back/side →
  front, so a **back decoration renders onto the front angle**. Audit the
  launch products and supply genuine Front/Back/Left/Right shots.
- ☐ **8.2.2** Confirm the curated launch subset (5–10 top-selling styles) with the client
- ☐ **8.2.3** Blank-hat sessions already carry all 4 angles — verify per hat type in §8.4

### 8.3 Admin users 🔴

- ☐ **8.3.1** `ADMIN_SECRET` is the un-deletable bootstrap super admin (no DB row) — keep it in the password manager, not in day-to-day use
- ☐ **8.3.2** Create named admin users for client staff (`admin_users` + `admin_user_stores`), each assigned to their store(s)
- ☐ **8.3.3** Verify a named admin can log in and sees **only** their assigned store
- ☐ **8.3.4** 🟡 Confirm the client has at least **two** admins (no single point of lockout)

### 8.4 Admin console configuration 🟡

Walk the client through each, or configure with them:

- ☐ **8.4.1** **Branding** — logo upload, primary colour, header bg/text, and the
  ≤5-item external main menu. Applies to the studio **and** to customer emails.
  > Note: `/storefront` brand lags **≤60s** after a save (stores cache TTL, no
  > bust-on-write). Don't debug a "not applied" that's just cache.
- ☐ **8.4.2** **Canvas intro copy** (`brand.canvas_intro`) — the v2 flow's intro text
- ☐ **8.4.3** **Hat Types** — create each blank hat type; 🔴 **all 4 angles must
  be uploaded before it can go `active`**. Set colourways, placement zones, decoration types.
- ☐ **8.4.4** **Decorations** — create the store's decoration methods
  (embroidery, print, …). 🔴 **If none are configured, the v2 `ask_decoration`
  step auto-skips** and the render-style bucket falls back to a default.
- ☐ **8.4.5** **Graphics** — upload any company graphics/patterns to offer customers
- ☐ **8.4.6** **Settings** — confirm `REGEN_EDITS_PER_SESSION` and
  `DESIGNS_PER_CUSTOMER_PER_DAY` (these are DB-backed via `app_settings` and
  **override** the env defaults once set)
- ☐ **8.4.7** **Canvas flow** — if using per-store step enable/reorder, confirm
  the safe subset (`ask_quantity` / `needed_by` / `ask_purpose`) is as the client wants

---

## §9. End-to-end verification & Shopify go-live

### 9.1 Full customer journey — customise flow 🔴

Run this as a **real customer**, on the production domain, in a clean browser
profile, with a **real inbox you control**:

- ☐ **9.1.1** Land via `?product_id=<shopify numeric id>` — correct product + photos render
- ☐ **9.1.2** Chat intro completes (name → email → …)
- ☐ **9.1.3** Verification email **arrives in the inbox, not spam**, within ~30s
- ☐ **9.1.4** Clicking the link shows the **store-branded** success page; the chat advances within one 4s poll cycle
- ☐ **9.1.5** Canvas unlocks; add **text**, an **uploaded logo**, a **shape**, and a **drawing**
- ☐ **9.1.6** Tick **Remove background** on the logo; the ✂ marker appears (nothing is matted client-side — by design)
- ☐ **9.1.7** Switch faces; thumbnails update live
- ☐ **9.1.8** "Done designing" → decoration + notes → generation starts
- ☐ **9.1.9** 🔴 A **real Gemini render** returns — not a stub placeholder — and the cap matches the reference photo
- ☐ **9.1.10** Multi-angle: every decorated face renders on its **own** product angle
- ☐ **9.1.11** Preview/quote email arrives with the inlined CID image rendering correctly
- ☐ **9.1.12** Quote request → reference code (`MH-XXXXXX`) emailed to customer
- ☐ **9.1.13** 🔴 Sales notification lands in `SALES_NOTIFICATION_EMAIL` with components attached
- ☐ **9.1.14** Admin-triggered render works: `POST /admin/quote-requests/{lead_id}/render`
- ☐ **9.1.15** Refine ("describe the change") edits the canvas and re-renders
- ☐ **9.1.16** Usage caps enforce (hit `DESIGNS_PER_CUSTOMER_PER_DAY` and confirm the block)

### 9.2 Blank-hat flow 🔴

- ☐ **9.2.1** `?mode=blank` → hat picker lists active hat types
- ☐ **9.2.2** Colour swatch tints the canvas; composite preview renders
- ☐ **9.2.3** Front hero AI-renders in the chosen colour; other angles come from the composite

### 9.3 Mobile 🟡

- ☐ **9.3.1** ⚠️ **The sub-768px stacked layout has never been observed
  in-browser** (documented open ticket — it rests on clamp arithmetic and
  class-pinning tests). **Verify on a real phone before go-live.** Check
  specifically: the Adjust panel is reachable above the cap, the canvas is
  usable, and the chat column doesn't crowd it out.
- ☐ **9.3.2** iOS Safari + Android Chrome, portrait and landscape
- ☐ **9.3.3** Touch drag/resize/rotate on the canvas
- ☐ **9.3.4** Image upload from the phone camera roll

### 9.4 Shopify storefront integration 🔴

- ☐ **9.4.1** Coordinate with the **MadHats in-house Shopify developer** — hard
  constraint: do not modify the live storefront unilaterally
- ☐ **9.4.2** 🔴 **InkyBay stays live and untouched.** The Studio sits alongside it.
- ☐ **9.4.3** Set `STUDIO_URL` at the top of `docs/shopify/studio-button.liquid`
  to the **`https://`** host (no port)
- ☐ **9.4.4** Install as a snippet (`snippets/madhats-studio-button.liquid` +
  `{% render 'madhats-studio-button' %}`) or a theme-editor **Custom Liquid**
  block on the product page
- ☐ **9.4.5** 🔴 Confirm the link passes **`{{ product.id }}`** (the Shopify
  numeric id, resolved against `product_references.shopify_product_id`) — **never
  the internal DB UUID**, which is regenerated on every catalogue re-sync
- ☐ **9.4.6** 🔴 **If the live button still points at
  `http://madhats.getaiconsult.com.au:5173/...`, repoint it to `https://`.** The
  old URL works *only* while the temporary legacy-redirect blocks stay in
  `caddy/Caddyfile.prod`. Once removed, an un-repointed button 404s for **every**
  customer.
- ☐ **9.4.7** Test on a **staging theme** first, then publish
- ☐ **9.4.8** Verify variant/colour params stay in sync when the customer switches variant
- ☐ **9.4.9** Test the button from a real product page on mobile and desktop

### 9.5 Post-cutover cleanup 🟢

- ☐ **9.5.1** After outstanding quote/verification tokens expire (~30 days),
  remove the "Legacy plain-HTTP ports" blocks from `caddy/Caddyfile.prod` and
  the `8000`/`5173` port mappings from `docker-compose.prod.yml`. Redeploy.
  **Do this only after 9.4.6 is confirmed.**
- ☐ **9.5.2** Raise DNS TTLs back to normal

---

# PART B — HANDOVER

---

## §10. Operational runbook (write this for the client, not for yourself)

- ☐ **10.1** 🔴 **Deploy procedure** documented — the exact `-f docker-compose.prod.yml`
  commands, including the rebuild-after-`VITE_API_BASE_URL`-change rule
- ☐ **10.2** 🔴 **Rollback procedure** — `git checkout <previous tag> && docker compose -f docker-compose.prod.yml up -d --build`; verified at least once
- ☐ **10.3** 🔴 **Self-heal sidecar explained** — the `watchdog` container hits
  `POST /admin/generations/reap-stuck` and `POST /admin/deliveries/backfill`
  every 180s over the compose network. **If it's down, stalled renders never
  recover and undelivered previews never retry.** Confirm it's running and
  document how to check.
- ☐ **10.4** 🟡 **Log access** — `docker compose -f docker-compose.prod.yml logs -f backend`; where Sentry lives; the no-PII rule
- ☐ **10.5** 🟡 **Common failure playbook**, at minimum:
  | Symptom | Cause | Fix |
  |---|---|---|
  | No images anywhere, mixed-content errors | `TRUSTED_PROXY_HOSTS` not reaching backend | §7.5 |
  | Browser calls `localhost:8000` | stale `VITE_API_BASE_URL` baked in | rebuild frontend |
  | Widespread 429s | same as above, or the nginx `X-Real-IP` relay is broken | §7.5, §7.2b |
  | `502 Bad Gateway` from nginx | compose stack down, or Caddy not on `127.0.0.1:8480` | §7.2b |
  | Blank page / empty 200, nginx healthy | Host mismatch at Caddy (`STUDIO_HOST`/`API_HOST` vs `server_name`) | §7.2b |
  | Cert expired / renewal failing | certbot timer (certs are nginx's now, not `caddy_data`) | §7.2 |
  | Designs never delivered | Gemini quota 429 / watchdog down | §4.3.5, §10.3 |
  | Customers can't finish the funnel | verification email in spam | §4.4 |
  | PostgREST `42703` on generation write | migration unapplied | §4.2.5 |
  | Compose won't start, port 80/443 taken | ran the **dev** stack by mistake | use `-f docker-compose.prod.yml` |
- ☐ **10.6** 🟡 **Backups verified by restore**, not just configured — Supabase
  PITR + a documented storage-bucket backup approach
- ☐ **10.7** 🟡 **Monitoring** — uptime check on `/health`, cert-expiry monitor, disk-space alert, Sentry alerts routed
- ☐ **10.8** 🟡 **Cost monitoring** — Gemini, Anthropic, Resend, Supabase, VPS: who watches the bills, what the alert thresholds are, and what the per-design cost is (`generations` logs cost + latency per image)
- ☐ **10.9** 🟢 **Key rotation procedure** for each provider key + `ADMIN_SECRET`
- ☐ **10.10** 🟢 **Onboarding a second store** documented (`POST /admin/stores` → `/sync` → new frontend build with that `VITE_STORE_KEY` — currently **one Studio deployment per store**)

---

## §11. Known gaps & open tickets — disclose these explicitly

🔴 **This section is a contractual honesty item.** The client must receive it in
writing, acknowledged, before sign-off. Handing over undisclosed known issues is
how handovers turn into disputes.

### 11.1 Functional gaps

- ☐ **11.1.1** **Resuming a v2 canvas session mid-design** (`?session=<token>`)
  doesn't rehydrate the canvas directive → the customer sees "Design locked in —
  finishing up" over a live design. Post-design resume is unaffected.
- ☐ **11.1.2** **No in-chat "resend verification link"** — if the email never
  arrives the customer must reload. Worth building if support tickets appear.
- ☐ **11.1.3** **Confirmed-edit ops are ephemeral** — a reload at the confirm
  gate loses them (only a flag is persisted, not the ops).
- ☐ **11.1.4** **A refused change request** gets no tailored acknowledgement —
  lands on the generic refine prompt.
- ☐ **11.1.5** **No `ANTHROPIC_API_KEY`** permanently stalls canvas
  `DESCRIBE_CHANGES` (that state ships no chips to escape with).
- ☐ **11.1.6** **Background-removal divergence:** if a customer *unticks* after
  the auto-mark, the step stays satisfied while the render reads the element's
  actual flag.
- ☐ **11.1.7** **Draw tool:** releasing the pointer off-stage discards the in-progress stroke (no window-level `mouseup` fallback).
- ☐ **11.1.8** **`/products` 1000-row cap** — needs pagination for large catalogues.
- ☐ **11.1.9** **Products with only a front image** alias back/side → front (§8.2.1).

### 11.2 Infrastructure / config gaps

- ☐ **11.2.1** **CORS is global, not per-store**, and currently open (`*`).
- ☐ **11.2.2** **Store brand cache lags ≤60s** after an admin save.
- ☐ **11.2.3** **Legacy plain-HTTP redirect ports** (`8000`/`5173`) still open — scheduled removal (§9.5).
- ☐ **11.2.4** **Missing index:** add a partial index on
  `leads(email_verified, preview_email_sent, verified_at)` before lead volume
  grows — the backfill/cron query will degrade without it.
- ☐ **11.2.5** **`BrandingView.FLOW_STEPS`** mirrors the backend's
  `CONFIGURABLE_STEP_IDS` by hand; a test warns on drift but nothing structurally couples them.

### 11.3 Cosmetic / accessibility

- ☐ **11.3.1** Adjust-panel accent header is a plain `<div>` (not a labelled
  region) and white-on-accent is ~3.1:1 contrast — **unbounded for a store that
  picks a pale primary colour**. Flag this when the client chooses branding.
- ☐ **11.3.2** Preview-email button shadow / edit-button text stay orange under a themed primary.
- ☐ **11.3.3** Verification + resume email **body copy still says "MadHats"** while the header is themed — matters for a second tenant.
- ☐ **11.3.4** Frontend test suite: 2 pre-existing `adminQuotes` failures (missing Router context).

### 11.4 Deliberate design decisions (not bugs — explain, don't fix)

- ☐ **11.4.1** **"Remove background" is a MARK, not an edit.** Nothing is matted
  client-side and nothing is re-uploaded; the flag travels to the image model,
  which does the knockout at render time. The customer copy must **never**
  promise processing or ask them to wait. **Do not reintroduce canvas-level
  processing.**
- ☐ **11.4.2** **Quote delivery is reference-only.** The customer is emailed the
  reference code, never the design. The promise of "the finished design with
  the quote" is kept by a **human** rendering it from the admin tools — not by code.
- ☐ **11.4.3** **Non-front faces are subject to model variability** — the real
  angle photo + layout guide keep them consistent, but they are AI-rendered, not
  pixel-exact flat mocks.
- ☐ **11.4.4** **Human-in-the-loop by design** — generated concepts are previews;
  the MadHats design team approves before production artwork.

---

## §12. Knowledge transfer

- ☐ **12.1** 🔴 **`CLAUDE.md` handed over as the primary technical document** —
  it is the single source of truth on architecture, constraints, and every
  landmine found in development. Walk the client's developer through it.
- ☐ **12.2** 🔴 **Live walkthrough session(s)**, recorded:
  - ☐ Architecture + data flow (customer → chat → canvas → generation → delivery → quote)
  - ☐ Admin console: every view, hands-on
  - ☐ Deploy + rollback, performed live by the client's engineer
  - ☐ Failure playbook (§10.5), with at least one fault injected and recovered
- ☐ **12.3** 🟡 **Client-facing operator guide** (non-technical): how to add a hat
  type, upload graphics, change branding, read the quote queue, handle a customer
  who says "my email never arrived"
- ☐ **12.4** 🟡 `docs/superpowers/specs/` + `plans/` indexed so future work has the design rationale
- ☐ **12.5** 🟡 The **hard constraints** (CLAUDE.md §2) restated in writing to the
  client — especially: composite onto real product photos, no customer face
  uploads, InkyBay untouched, models swappable via env, no secrets in code, no
  PII in logs
- ☐ **12.6** 🟢 Named technical contact on the client side identified and trained

---

## §13. Ownership transfer

> ⚠️ **Sequence matters.** Transfer ownership **before** you remove your own
> access, and verify the client can operate independently **before** the support
> window starts counting down.

### 13.1 Source control 🔴

- ☐ **13.1.1** Client has a GitHub organisation (or nominated account) ready
- ☐ **13.1.2** Transfer the repo: **Settings → General → Danger Zone → Transfer ownership**
- ☐ **13.1.3** Client **accepts** the transfer (it's a two-sided handshake — it can sit pending)
- ☐ **13.1.4** Verify: tags, branches, issues, and full history survived
- ☐ **13.1.5** Re-point the server's remote if the URL changed; re-add the deploy key under the new owner
- ☐ **13.1.6** Confirm the server can still `git pull` **after** transfer
- ☐ **13.1.7** Client adds their own collaborators; you are added as an outside collaborator for the support window only

### 13.2 Service accounts 🔴

For each of Supabase, Anthropic, Google/Gemini, Resend, Sentry, the VPS host,
and the domain registrar:

- ☐ **13.2.1** Ownership transferred **or** account recreated under client billing
- ☐ **13.2.2** Billing method moved to the client
- ☐ **13.2.3** 🔴 If an account was **recreated**, keys change — update `.env`,
  redeploy, and **re-verify §9.1 end-to-end**. This is not a paperwork step.
- ☐ **13.2.4** Spend alerts re-pointed to the client's inbox
- ☐ **13.2.5** Resend domain verification still valid under the new account

### 13.3 Credentials 🔴

- ☐ **13.3.1** All secrets delivered via a **password manager share or encrypted
  vault** — never email, never chat, never a spreadsheet
- ☐ **13.3.2** Inventory delivered: every key, its purpose, where it's set, and how to rotate it
- ☐ **13.3.3** 🔴 **Rotate `ADMIN_SECRET` and `ADMIN_JWT_SECRET` at handover** —
  the client should hold values you have never used
- ☐ **13.3.4** Server SSH: client's keys added; your key **removed at the end of the support window** (13.5.3)
- ☐ **13.3.5** Supabase service-role key rotated if it was ever shared outside the vault

### 13.4 Shopify 🟡

- ☐ **13.4.1** Any collaborator/staff access you hold is documented
- ☐ **13.4.2** The in-house Shopify developer owns the storefront snippet going forward
- ☐ **13.4.3** Your Shopify access removed at the end of the support window

### 13.5 Access wind-down 🟢

- ☐ **13.5.1** Support window agreed and dated: **from ______ to ______**
- ☐ **13.5.2** Client confirms they have deployed once **unaided**
- ☐ **13.5.3** Your access removed from: GitHub, server SSH, Supabase, Resend, Sentry, Shopify, GCP/Anthropic
- ☐ **13.5.4** Confirm in writing that access removal is complete

---

## §14. Sign-off

| Item | Confirmed by | Date |
|---|---|---|
| Part A complete — system live and verified (§1–§9) | | |
| Known gaps disclosed and acknowledged (§11) | | |
| Knowledge transfer complete (§12) | | |
| Repository ownership transferred and accepted (§13.1) | | |
| Service accounts + billing transferred (§13.2) | | |
| Credentials delivered and rotated (§13.3) | | |
| Client has deployed unaided (§13.5.2) | | |
| Support window start / end | | |
| **Final handover accepted** | | |

---

## Appendix A — Quick command reference

```bash
# ---- Production deploy ----
cd ~/madhats-aidesign && git pull
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d --build

# Rebuild frontend ONLY (required after any VITE_* change — it is compiled in)
docker compose -f docker-compose.prod.yml up -d --build frontend

# Rebuild backend (built image, no bind-mount — code changes need a build)
docker compose -f docker-compose.prod.yml up -d --build backend

# ---- Status / logs ----
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml exec backend env | grep TRUSTED

# ---- Health ----
curl -s  https://api.madhats.getaiconsult.com.au/health
curl -sI https://madhats.getaiconsult.com.au

# ---- Verify the baked-in API URL ----
docker compose -f docker-compose.prod.yml exec frontend \
  sh -c "grep -o 'https://api\.[a-z0-9.-]*' /app/dist/assets/*.js | head"

# ---- Admin (X-Admin-Secret on every call) ----
curl -X POST -H "X-Admin-Secret: $ADMIN_SECRET" $API/admin/stores
curl -X POST -H "X-Admin-Secret: $ADMIN_SECRET" $API/admin/stores/$ID/sync
curl -X POST -H "X-Admin-Secret: $ADMIN_SECRET" $API/admin/generations/reap-stuck
curl -X POST -H "X-Admin-Secret: $ADMIN_SECRET" $API/admin/deliveries/backfill
curl      -H "X-Admin-Secret: $ADMIN_SECRET" $API/admin/quote-requests

# ---- Rollback ----
git checkout <previous-tag>
docker compose -f docker-compose.prod.yml up -d --build
```

## Appendix B — The five mistakes that cost the most time

1. **Running certbot before DNS resolves** → burns the Let's Encrypt
   duplicate-cert limit (5/week) and blocks issuance for the real domain.
2. **Recreating instead of rebuilding the frontend** after a `VITE_API_BASE_URL`
   change → total outage that looks like a backend fault.
3. **`TRUSTED_PROXY_HOSTS` not reaching the backend** → no imagery renders
   anywhere, plus shared rate-limit buckets and mass 429s.
4. **Running the dev compose file on the prod box** → port collisions, an
   untrusted internal CA, and an `api.localhost` API URL.
5. **Unapplied Supabase migrations** → PostgREST `42703` at runtime, not at
   deploy. Always verify columns exist, never assume `db push` ran.
