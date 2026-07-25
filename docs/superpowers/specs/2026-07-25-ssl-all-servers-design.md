# SSL/TLS for all servers (prod + dev) — design

**Date:** 2026-07-25
**Status:** approved, ready for planning

## Goal

Serve the backend and frontend over HTTPS in both the production stack
(`docker-compose.prod.yml`) and the dev stack (`docker-compose.yml`), replacing
the current plain-HTTP `madhats.getaiconsult.com.au:8000` / `:5173`.

Two drivers:

1. The studio is embedded in an HTTPS Shopify storefront; plain-HTTP endpoints
   are mixed content.
2. The microphone / Web Speech API requires a secure context.
   `frontend/vite.config.ts:1-10` already documents a `tailscale serve`
   workaround that exists solely to obtain one — this replaces that hack with a
   first-class path.

## Non-goals

- **CORS lockdown.** `ALLOWED_ORIGINS` stays `*` (see "Deliberately unchanged").
- Certificates for anything other than the two web servers. Supabase is hosted
  and already HTTPS; internal compose-network traffic stays plain HTTP.
- Any change to application behaviour, data, or the conversation engines.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Cert authority (prod) | Let's Encrypt via Caddy, HTTP-01 | Direct A record, DNS under our control, ports 80/443 free |
| Cert authority (dev) | Caddy `tls internal` | Same proxy config as prod, so routing bugs surface locally |
| URL shape | Two subdomains on 443 | No path rewriting, no route collisions, standard ports |
| Proxy | Caddy | Automatic ACME + renewal + 80→443 redirect, no cron |

### URL shape

```
https://madhats.getaiconsult.com.au       -> frontend:5173
https://api.madhats.getaiconsult.com.au   -> backend:8000

https://localhost                         -> frontend:5173   (dev)
https://api.localhost                     -> backend:8000    (dev)
```

Requires one new DNS record: `api.madhats` A → box public IP.

Two subdomains were chosen over single-host `/api/*` path routing because the
frontend already owns a React route at `/admin` while the backend serves its
admin API at `/admin/*`. Under path routing the `/api` prefix would be the only
thing preventing that collision — load-bearing, and easy to break later.
Separate origins make the collision structurally impossible.

Non-standard ports over TLS (`https://…:8000`) were rejected: blocked by some
corporate proxies and captive-portal wifi.

## Architecture

```
                      :80 ─┐ (301 -> :443)
  internet ──────────► :443 ── caddy ──┬─► frontend:5173
                      :8000 ┘          └─► backend:8000
                      :5173 ┘ (legacy redirects, see Migration)
```

`caddy` becomes the **only** service publishing ports to the host. `backend` and
`frontend` drop their `ports:` mappings and are reachable only on the compose
network.

This is load-bearing, not tidiness: if `8000:8000` survives, then
`http://madhats.getaiconsult.com.au:8000` continues to serve the entire API in
cleartext, and the TLS in front of it is decorative.

### Caddyfile

One file, site blocks selected per environment.

```caddyfile
# --- production ---
madhats.getaiconsult.com.au {
    reverse_proxy frontend:5173
}
api.madhats.getaiconsult.com.au {
    reverse_proxy backend:8000
}

# --- dev ---
localhost {
    tls internal
    reverse_proxy frontend:5173
}
api.localhost {
    tls internal
    reverse_proxy backend:8000
}
```

Caddy sets `X-Forwarded-For` / `X-Forwarded-Proto` on proxied requests by
default, which the backend fix below depends on.

### Cert persistence — mandatory

The `caddy` service needs a named volume mounted at `/data`. That is where
issued certificates and ACME account keys are stored.

Without it, every `docker compose up` re-issues from scratch. Let's Encrypt
permits 5 duplicate certificates per week; exceeding that locks out issuance for
our own domain for the remainder of the window.

## The rate-limiting defect this introduces

`backend/app/api/deps.py:17` constructs `Limiter(key_func=get_remote_address)`.
`slowapi.util.get_remote_address` reads `request.client.host`.

Once traffic arrives via Caddy, `request.client.host` is **the proxy's container
IP on every request**. All customers therefore collapse into a single
rate-limit bucket, and `RATE_LIMIT_RPM` silently becomes a site-wide cap rather
than a per-client one. One busy session 429s everybody else.

It fails quietly — no error, no log, just throttling that looks like load.

**Fix** — `backend/Dockerfile:17`, and the dev stack's uvicorn command:

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
```

`--proxy-headers` is on by default in current uvicorn, but
`--forwarded-allow-ips` defaults to `127.0.0.1`, which never matches a container
IP — so the explicit flag is required regardless. `*` is safe here precisely
because the port mappings were dropped: Caddy is the only thing that can reach
the port.

**Test:** a request carrying `X-Forwarded-For` must key the limiter on the
forwarded client IP, not the immediate peer.

## Configuration

Four values move to HTTPS. All live in the project-root `.env`.

| Var | Defined at | Prod | Dev |
|---|---|---|---|
| `VITE_API_BASE_URL` | `frontend/Dockerfile:26` (build arg) | `https://api.madhats.getaiconsult.com.au` | `https://api.localhost` |
| `EMAIL_VERIFY_BASE_URL` | `backend/app/config.py:72` | `https://api.madhats.getaiconsult.com.au` | `https://api.localhost` |
| `STUDIO_BASE_URL` | `backend/app/config.py:75` | `https://madhats.getaiconsult.com.au` | `https://localhost` |
| `ALLOWED_ORIGINS` | `backend/app/main.py:69` | `*` (unchanged) | `*` (unchanged) |

`EMAIL_VERIFY_BASE_URL` backs the verification and quote links in customer
email. `STUDIO_BASE_URL` backs the resume link (`backend/app/api/routes/leads.py:204`).
Both are absolute URLs baked into sent mail — see Migration.

### Rebuild ordering trap

`VITE_API_BASE_URL` is inlined into the JS bundle by Vite at **build** time. The
frontend must be rebuilt, not merely recreated:

```bash
docker compose -f docker-compose.prod.yml up -d --build frontend
```

Recreating alone leaves the old `http://…:8000` compiled in, and every API call
then fails as mixed content from an HTTPS page — a total outage that looks like
a backend fault.

## Migration: in-flight customer emails

Verification and quote links already delivered to customers point at
`http://madhats.getaiconsult.com.au:8000/...` with signed tokens. Dropping the
port mapping dead-ends every one of them.

Caddy therefore also listens on `:8000` and `:5173` and issues 301 redirects to
the corresponding HTTPS URLs, preserving path and query so signed tokens
survive. This is a deprecation window, removable once outstanding tokens have
expired.

## Deliberately unchanged

- **`ALLOWED_ORIGINS` stays `*`.** Locking CORS is a real improvement but an
  independent one; bundling it into a TLS migration doubles the blast radius of
  a single deploy. It also needs a prior check on whether the Shopify widget
  issues any request from the `madhats.com.au` parent origin rather than from
  inside the studio iframe. Remains tracked as a known gap in CLAUDE.md §3b.
- **The `watchdog` sidecar** keeps calling `http://backend:8000` over the compose
  network. Internal traffic should not pay for TLS termination, and the hostname
  is not publicly resolvable anyway.
- **Application code.** No route, service, or conversation-engine changes.

## Dev stack specifics

- `frontend/vite.config.ts` gains an HMR branch for the Caddy proxy
  (`{ protocol: 'wss', clientPort: 443 }`), mirroring the existing
  `TAILSCALE_HOST` branch at lines 50-53.
- Trusting the internal CA requires extracting the root from the container:
  ```bash
  docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
  # then import into the Windows Trusted Root Certification Authorities store
  ```
  `caddy trust` alone does not work when Caddy runs in Docker — the CA lives
  inside the container, not on the host.
- `*.localhost` resolves to `127.0.0.1` natively in Chrome and Firefox; no
  hosts-file edit is needed.
- The existing `TAILSCALE_HOST` path is retained and untouched, so phone-on-tailnet
  testing keeps working.

## Verification

1. `curl -vI https://madhats.getaiconsult.com.au` and the `api.` host — valid
   chain, HTTP/2, no warnings.
2. `curl -I http://madhats.getaiconsult.com.au` → 301 to HTTPS.
3. Legacy `http://…:8000/<path>?<query>` → 301 preserving path and query.
4. Backend test suite, including the new forwarded-IP rate-limit test.
5. End-to-end customer run: chat → email verification link → quote link →
   studio resume link. This is the only check that exercises all three URL
   variables together.
6. Microphone in the studio — confirms the secure context, the original driver.
7. Browser devtools: no mixed-content warnings, no CORS errors.

## Rollback

Revert the compose files, `backend/Dockerfile`, `vite.config.ts`, and `.env`,
then `docker compose -f docker-compose.prod.yml up -d --build`. No schema
migration, no data mutation, nothing destructive. Legacy HTTP URLs in already-sent
email resume working immediately on rollback because the port mappings return.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Cert volume omitted → ACME rate-limit lockout | High | Named `/data` volume; verified in the plan's acceptance checks |
| Rate limiter keys on proxy IP | High | `--forwarded-allow-ips`, plus a regression test |
| Frontend recreated but not rebuilt | High | Documented in compose header comments and the runbook |
| In-flight email links dead-end | Medium | Legacy `:8000`/`:5173` redirect window |
| `api.` DNS record not yet propagated at deploy | Medium | Confirm resolution before the first `up`; ACME fails without it |
