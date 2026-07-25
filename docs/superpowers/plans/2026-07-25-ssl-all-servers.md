# SSL/TLS for All Servers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the backend and frontend over HTTPS in both the production and dev Docker stacks, via a Caddy reverse proxy that terminates TLS.

**Architecture:** A new `caddy` service becomes the only port-publishing container in each stack. It reverse-proxies two hostnames to the existing `frontend:5173` and `backend:8000` services over the internal compose network. Production uses Let's Encrypt (HTTP-01); dev uses Caddy's internal CA. The backend gains a `ProxyHeadersMiddleware` so per-client rate limiting survives the new hop.

**Tech Stack:** Caddy 2 (alpine image), Docker Compose, FastAPI/uvicorn, Vite.

**Spec:** `docs/superpowers/specs/2026-07-25-ssl-all-servers-design.md`

## Global Constraints

- **`ALLOWED_ORIGINS` stays `*`.** Do not change CORS in this work. It is an explicit non-goal of the spec.
- **No secrets in code.** All values via env vars (CLAUDE.md §8.1).
- **Do not touch application behaviour** — no route, service, or conversation-engine changes.
- **Backend tests must be run as** `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`. The repo-root `.env` defaults that flag to `true`, which flips 3 unrelated tests red. Baseline is **954 passing**.
- **The `watchdog` sidecar keeps using `http://backend:8000`** over the compose network. Do not route it through Caddy.
- Windows host, Git Bash. Backend venv is at `backend/.venv/Scripts/python.exe`.

## Two deviations from the spec (deliberate, verified)

1. **The proxy-header fix is app-level middleware, not the Dockerfile CLI flags the spec proposed.** The spec's `--proxy-headers --forwarded-allow-ips=*` would work, but `TestClient` never runs uvicorn's CLI, so it is untestable and would silently regress. `ProxyHeadersMiddleware` added in `create_app()` is testable, and applies under any launcher. Verified empirically: without it `get_remote_address` returns `testclient`; with it, `203.0.113.9` from `X-Forwarded-For`. **No Dockerfile or compose `command` change is needed.**

2. **Two Caddyfiles, not one.** The spec said "one Caddyfile, site blocks per environment". A single file containing the production hostnames would make the **dev** stack attempt ACME issuance for `madhats.getaiconsult.com.au` on every startup — failing, and burning Let's Encrypt rate limits against the real domain. Split into `caddy/Caddyfile.prod` and `caddy/Caddyfile.dev`, each mounted by its own compose file. The dev file additionally sets the `local_certs` global option so it *cannot* reach ACME even if edited carelessly.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/app/config.py` | Modify | Add `trusted_proxy_hosts` setting + parsing property |
| `backend/app/main.py` | Modify | Register `ProxyHeadersMiddleware` as outermost middleware |
| `backend/tests/test_proxy_headers.py` | Create | Regression tests for forwarded-IP keying and middleware order |
| `caddy/Caddyfile.prod` | Create | Production site blocks + legacy port redirects |
| `caddy/Caddyfile.dev` | Create | Dev site blocks, internal CA only |
| `docker-compose.prod.yml` | Modify | Add `caddy` service + volumes; drop backend/frontend port mappings |
| `docker-compose.yml` | Modify | Add `caddy` service + volumes for dev |
| `frontend/vite.config.ts` | Modify | HMR over the TLS proxy (`wss`, port 443) |
| `.env.example` | Modify | Document the new and changed variables |
| `CLAUDE.md` | Modify | Update the §13c deployment runbook |

---

### Task 1: Trust the reverse proxy (backend)

Without this, every request arrives at the backend with `request.client.host` set to Caddy's container IP. `slowapi`'s `get_remote_address` reads exactly that field (`backend/app/api/deps.py:17` → `Limiter(key_func=get_remote_address)`), so all customers collapse into one rate-limit bucket and `RATE_LIMIT_RPM` becomes a site-wide cap. It fails silently — no error, just 429s that look like load.

**Files:**
- Modify: `backend/app/config.py:63-65` (add setting near `allowed_origins`), `backend/app/config.py:84` (add property)
- Modify: `backend/app/main.py:12-15` (import), `backend/app/main.py:113-116` (register)
- Test: `backend/tests/test_proxy_headers.py`

**Interfaces:**
- Produces: `Settings.trusted_proxy_hosts: str` (default `"*"`), `Settings.trusted_proxy_hosts_value -> list[str] | str`. No later task consumes these from Python; Task 4 documents the env var `TRUSTED_PROXY_HOSTS`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_proxy_headers.py`. This follows the pattern of `backend/tests/test_cors.py`, which builds minimal apps rather than depending on the ambient `.env`.

```python
"""Behind a reverse proxy, the client IP must come from X-Forwarded-For.

slowapi keys rate limits on `request.client.host` (see app/api/deps.py:
`Limiter(key_func=get_remote_address)`). Once Caddy terminates TLS in front of
the backend, that field is the PROXY's container IP on every request — which
silently collapses every customer into a single rate-limit bucket, turning
RATE_LIMIT_RPM into a site-wide cap. ProxyHeadersMiddleware rewrites it.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi.util import get_remote_address
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import Settings


def _app(*, trusted: str | list[str] | None) -> FastAPI:
    """Minimal app exposing whatever slowapi would key a rate limit on."""
    app = FastAPI()

    @app.get("/whoami")
    def whoami(request: Request):  # noqa: ANN202
        return {"ip": get_remote_address(request)}

    if trusted is not None:
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted)
    return app


FORWARDED = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"}


def test_without_the_middleware_the_forwarded_ip_is_ignored():
    """Documents the bug this middleware exists to prevent."""
    resp = TestClient(_app(trusted=None)).get("/whoami", headers=FORWARDED)
    assert resp.json()["ip"] == "testclient"


def test_forwarded_for_becomes_the_rate_limit_key():
    resp = TestClient(_app(trusted="*")).get("/whoami", headers=FORWARDED)
    assert resp.json()["ip"] == "203.0.113.9"


def test_direct_request_without_forwarded_header_is_unaffected():
    resp = TestClient(_app(trusted="*")).get("/whoami")
    assert resp.json()["ip"] == "testclient"


def test_two_clients_behind_the_proxy_get_distinct_keys():
    """The actual regression: distinct customers must not share a bucket."""
    client = TestClient(_app(trusted="*"))
    a = client.get("/whoami", headers={"X-Forwarded-For": "198.51.100.1"}).json()
    b = client.get("/whoami", headers={"X-Forwarded-For": "198.51.100.2"}).json()
    assert a["ip"] != b["ip"]


def test_default_trusts_no_proxy():
    """Fail SAFE. Trusting a forwarded header from an untrusted caller is worse
    than the bug this fixes: anyone reaching the port directly could rotate
    X-Forwarded-For for a fresh rate-limit bucket per request. The deployment
    that closes the port is the deployment that opts in (docker-compose.prod.yml)."""
    assert Settings().trusted_proxy_hosts == ""
    assert Settings().trusted_proxy_hosts_value == []


def test_untrusted_forwarded_header_is_ignored():
    resp = TestClient(_app(trusted=[])).get("/whoami", headers=FORWARDED)
    assert resp.json()["ip"] == "testclient"


def test_wildcard_is_honoured_when_explicitly_configured():
    assert Settings(trusted_proxy_hosts="*").trusted_proxy_hosts_value == "*"


def test_trusted_proxy_hosts_parses_a_comma_list():
    s = Settings(trusted_proxy_hosts="10.0.0.1, 10.0.0.2")
    assert s.trusted_proxy_hosts_value == ["10.0.0.1", "10.0.0.2"]


def test_proxy_headers_is_the_outermost_middleware():
    """Starlette's add_middleware inserts at index 0, so the LAST-added runs
    FIRST. ProxyHeadersMiddleware must be outermost, otherwise SlowAPIMiddleware
    reads request.client.host before it has been rewritten."""
    from app.main import app

    assert app.user_middleware[0].cls is ProxyHeadersMiddleware
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_proxy_headers.py -q
```

Expected: the four `_app`-based tests **pass already** (they exercise the library directly, and are there to pin the behaviour). The three failures are:
- `test_trusted_proxy_hosts_defaults_to_wildcard` → `ValidationError` / `AttributeError: 'Settings' object has no attribute 'trusted_proxy_hosts_value'`
- `test_trusted_proxy_hosts_parses_a_comma_list` → same
- `test_proxy_headers_is_the_outermost_middleware` → `AssertionError` (currently `CORSMiddleware`)

- [ ] **Step 3: Add the setting**

In `backend/app/config.py`, immediately after the `allowed_origins` block (currently lines 63-65):

```python
    # Hosts whose X-Forwarded-* headers are trusted, for ProxyHeadersMiddleware.
    #
    # Defaults to trusting NOTHING, deliberately. Honouring X-Forwarded-For from
    # an untrusted caller is worse than the bucket-collapse it prevents: anyone
    # who can reach this port directly could rotate the header for a fresh
    # rate-limit bucket per request. Only a deployment that puts a proxy in front
    # AND stops publishing the port may opt in — docker-compose.prod.yml sets
    # "*" immediately beside the removed port mapping, so the trust and its
    # justification live on the same screen.
    trusted_proxy_hosts: str = ""
```

And with the other properties, after `allow_all_origins` (currently ends line 91):

```python
    @property
    def trusted_proxy_hosts_value(self) -> list[str] | str:
        """Matches ProxyHeadersMiddleware's `trusted_hosts`, which accepts either
        the literal "*" or a list of hosts."""
        raw = self.trusted_proxy_hosts.strip()
        if raw == "*":
            return "*"
        return [h.strip() for h in raw.split(",") if h.strip()]
```

- [ ] **Step 4: Register the middleware**

In `backend/app/main.py`, add to the imports (after line 15, `from slowapi.middleware import SlowAPIMiddleware`):

```python
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
```

Then in `create_app()`, immediately after the CORS line (currently line 116, `app.add_middleware(CORSMiddleware, **build_cors_kwargs(settings))`):

```python
    # Trust the reverse proxy's X-Forwarded-* headers.
    #
    # MUST be added LAST: Starlette's add_middleware inserts at index 0, so the
    # last-added middleware is the OUTERMOST one. SlowAPIMiddleware keys rate
    # limits on request.client.host, which behind Caddy is the proxy's container
    # IP — every customer would share one bucket until this rewrites it.
    app.add_middleware(
        ProxyHeadersMiddleware, trusted_hosts=settings.trusted_proxy_hosts_value
    )
```

- [ ] **Step 5: Run the new tests to verify they pass**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_proxy_headers.py -q
```

Expected: 7 passed.

- [ ] **Step 6: Run the full backend suite for regressions**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q
```

Expected: **961 passed** (954 baseline + 7 new). Any other change is a regression — most likely from middleware ordering. Stop and investigate rather than adjusting the assertion.

- [ ] **Step 7: Commit**

```bash
git add backend/app/config.py backend/app/main.py backend/tests/test_proxy_headers.py
git commit -m "fix(backend): key rate limits on the forwarded client IP

Behind a reverse proxy, request.client.host is the proxy's container IP,
so slowapi's get_remote_address collapsed every customer into one
rate-limit bucket -- turning RATE_LIMIT_RPM into a site-wide cap that
fails silently. Register ProxyHeadersMiddleware as the outermost
middleware so X-Forwarded-For is honoured before SlowAPIMiddleware runs.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Production Caddy

**Files:**
- Create: `caddy/Caddyfile.prod`
- Modify: `docker-compose.prod.yml:30-56` (services), plus a new top-level `volumes:` block

**Interfaces:**
- Consumes: nothing from Task 1 at the code level (Task 1 is what makes this safe to deploy).
- Produces: service name `caddy`; named volumes `caddy_data`, `caddy_config`; env var `ACME_EMAIL` (documented in Task 4).

- [ ] **Step 1: Create the production Caddyfile**

Create `caddy/Caddyfile.prod`:

```caddyfile
# Production TLS termination.
#
# Certificates are obtained from Let's Encrypt over HTTP-01 automatically, and
# renewed without a cron job. Caddy also redirects :80 -> :443 by itself.
#
# REQUIRED: the `caddy_data` volume must be mounted at /data. That is where
# issued certificates and the ACME account key live. Without it every restart
# re-issues from scratch, and Let's Encrypt's limit of 5 duplicate certificates
# per week will lock us out of our own domain.

{
	# Address Let's Encrypt uses for certificate-expiry notices.
	#
	# REQUIRED, and enforced by docker-compose.prod.yml's `${ACME_EMAIL:?...}`.
	# Caddy's `email` directive rejects an empty argument at PARSE time
	# ("wrong argument count"), so a blank value does not degrade to "no
	# notices" — it stops the proxy from starting at all, taking the whole
	# site down on a fresh deploy. Compose therefore refuses to start with a
	# clear message rather than letting Caddy fail cryptically.
	email {$ACME_EMAIL}
}

madhats.getaiconsult.com.au {
	reverse_proxy frontend:5173
}

api.madhats.getaiconsult.com.au {
	reverse_proxy backend:8000
}

# --- Legacy plain-HTTP ports: redirect-only, temporary ------------------------
# Verification and quote links ALREADY DELIVERED to customers point at
# http://madhats.getaiconsult.com.au:8000/... with signed tokens. Dropping these
# ports would dead-end every one of them. {uri} preserves path AND query, so the
# tokens survive the redirect.
#
# These blocks are address-only (no hostname), so Caddy serves them over plain
# HTTP and does not attempt certificates for them.
#
# REMOVE once outstanding tokens have expired: the longest-lived is the quote
# token at QUOTE_TOKEN_TTL_SECONDS = 2592000 (30 days).

:8000 {
	redir https://api.madhats.getaiconsult.com.au{uri} permanent
}

:5173 {
	redir https://madhats.getaiconsult.com.au{uri} permanent
}
```

- [ ] **Step 2: Validate the Caddyfile syntax**

```bash
docker run --rm -v "//c/Users/satis/madhats-aidesign/caddy/Caddyfile.prod:/etc/caddy/Caddyfile:ro" \
  caddy:2.8-alpine caddy validate --config /etc/caddy/Caddyfile
```

Expected: `Valid configuration`. (The leading `//` on the path is the Git Bash escape that stops MSYS from mangling it into a Windows path.)

- [ ] **Step 3: Add the caddy service to `docker-compose.prod.yml`**

Insert this service after the `frontend` service (i.e. after current line 56):

```yaml
  # TLS termination for both web services. The ONLY container publishing ports.
  caddy:
    image: caddy:2.8-alpine
    restart: unless-stopped
    ports:
      - "80:80"     # ACME HTTP-01 challenge + redirect to 443
      - "443:443"
      - "8000:8000" # legacy redirect only — see Caddyfile.prod, remove after 30d
      - "5173:5173" # legacy redirect only — see Caddyfile.prod, remove after 30d
    environment:
      # `:?` makes compose refuse to start with this message when the value is
      # missing. Required because Caddy's `email` directive rejects a blank
      # argument at parse time — a silent default would take the site down.
      ACME_EMAIL: ${ACME_EMAIL:?set ACME_EMAIL in .env - Caddy needs it for Let us Encrypt expiry notices}
    volumes:
      - ./caddy/Caddyfile.prod:/etc/caddy/Caddyfile:ro
      - caddy_data:/data      # MANDATORY: issued certs live here
      - caddy_config:/config
    depends_on:
      - backend
      - frontend
```

Then add a top-level block at the very end of the file:

```yaml
volumes:
  caddy_data:
  caddy_config:
```

- [ ] **Step 4: Remove the backend and frontend port mappings**

In `docker-compose.prod.yml`, delete these two lines from the `backend` service (currently lines 34-35):

```yaml
    ports:
      - "8000:8000"
```

and these two from `frontend` (currently lines 52-53):

```yaml
    ports:
      - "5173:5173" 
```

This is load-bearing, not tidiness: if `8000:8000` survives, `http://madhats.getaiconsult.com.au:8000` keeps serving the whole API in cleartext and the TLS in front of it is decorative.

**In the same edit**, add the proxy-trust opt-in to the `backend` service, so the trust and the port closure that justifies it sit together:

```yaml
    environment:
      # Safe ONLY because this service publishes no ports (see above): the Caddy
      # container is the only thing that can reach 8000, so X-Forwarded-For
      # cannot be spoofed. Re-add a `ports:` mapping and this becomes a
      # rate-limit bypass — anyone could rotate the header for a fresh bucket.
      TRUSTED_PROXY_HOSTS: "*"
```

Without this line the backend trusts no proxy (Task 1 defaults it to empty), so `request.client.host` stays Caddy's container IP and every customer shares one rate-limit bucket.

Both services remain reachable from Caddy over the compose network by service name; no `expose:` is needed (Docker Compose networks allow all inter-service ports by default).

- [ ] **Step 5: Verify the compose file parses and the ports moved**

```bash
cd /c/Users/satis/madhats-aidesign
docker compose -f docker-compose.prod.yml config > /dev/null && echo "COMPOSE OK"
docker compose -f docker-compose.prod.yml config | grep -A3 "published"
```

Expected: `COMPOSE OK`, and every published port belongs to the `caddy` service — none under `backend` or `frontend`.

- [ ] **Step 6: Update the header comment block**

Replace the usage notes at the top of `docker-compose.prod.yml` (lines 11-28) so they describe the new topology. Add these two facts, which are the ones that cause outages:

```
#   - caddy is the only service publishing ports. backend/frontend are reachable
#     only on the compose network. Re-adding a `ports:` mapping to either one
#     re-exposes it in cleartext AND makes TRUSTED_PROXY_HOSTS=* spoofable.
#   - VITE_API_BASE_URL is COMPILED IN. After changing it you must REBUILD, not
#     just recreate:  docker compose -f docker-compose.prod.yml up -d --build frontend
#     Recreating alone leaves the old http:// URL in the bundle, and every API
#     call then fails as mixed content from the HTTPS page.
```

- [ ] **Step 7: Commit**

```bash
git add caddy/Caddyfile.prod docker-compose.prod.yml
git commit -m "feat(infra): terminate TLS with Caddy in the production stack

Caddy becomes the only port-publishing service, reverse-proxying two
hostnames to frontend:5173 and backend:8000. Let's Encrypt HTTP-01 with
automatic renewal; certs persisted in a named volume so restarts do not
re-issue and trip the duplicate-certificate rate limit.

Legacy :8000/:5173 listeners 301 to HTTPS preserving path and query, so
verification and quote links already sitting in customer inboxes keep
resolving until their tokens expire.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Dev Caddy + HMR over TLS

The point of this task is that the dev stack exercises the same proxy configuration as production, so routing mistakes surface locally. It also gives the microphone a secure context without Tailscale — `frontend/vite.config.ts:1-10` documents that the `tailscale serve` workaround exists for exactly this reason.

**Files:**
- Create: `caddy/Caddyfile.dev`
- Modify: `docker-compose.yml` (add `caddy` service + `volumes:` block)
- Modify: `frontend/vite.config.ts:11` (new env read), `:26-28` (allowed hosts), `:50-53` (HMR branch)

**Interfaces:**
- Consumes: the `caddy` service shape from Task 2.
- Produces: env var `TLS_PROXY_HOST` (documented in Task 4).

- [ ] **Step 1: Create the dev Caddyfile**

Create `caddy/Caddyfile.dev`:

```caddyfile
# Dev TLS termination, mirroring Caddyfile.prod so proxy/routing bugs surface
# locally instead of in production.
#
# `local_certs` forces Caddy's INTERNAL CA for every site. This is deliberately
# a global option rather than a per-site `tls internal`: it makes it impossible
# for this file to contact Let's Encrypt even if a real hostname is added to it
# by mistake, which would otherwise burn ACME rate limits against the live domain.
#
# *.localhost resolves to 127.0.0.1 natively in Chrome and Firefox — no hosts
# file edit is needed.

{
	local_certs
}

localhost {
	reverse_proxy frontend:5173
}

api.localhost {
	reverse_proxy backend:8000
}
```

Caddy v2's `reverse_proxy` handles WebSocket upgrades automatically, so Vite's HMR socket needs no extra directive here.

- [ ] **Step 2: Validate it**

```bash
docker run --rm -v "//c/Users/satis/madhats-aidesign/caddy/Caddyfile.dev:/etc/caddy/Caddyfile:ro" \
  caddy:2.8-alpine caddy validate --config /etc/caddy/Caddyfile
```

Expected: `Valid configuration`.

- [ ] **Step 3: Add the caddy service to `docker-compose.yml`**

Insert after the `frontend` service (i.e. after current line 55, before the `watchdog` comment):

```yaml
  # TLS termination for dev, using Caddy's internal CA. Mirrors the prod stack
  # so proxy/routing bugs surface here first.
  #   https://localhost      -> frontend
  #   https://api.localhost  -> backend
  caddy:
    image: caddy:2.8-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./caddy/Caddyfile.dev:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - backend
      - frontend
```

And a top-level block at the end of the file:

```yaml
volumes:
  caddy_data:
  caddy_config:
```

**Unlike prod, dev KEEPS the `backend`/`frontend` port mappings** (`8000:8000`, `5173:5173`) so `http://localhost:5173` still works for a quick check without the proxy.

Add the proxy-trust opt-in to the dev `backend` service too, in its existing `environment:` block (after the `SUPABASE_URL` entry), so dev exercises the same client-IP path as prod:

```yaml
      # Dev opts in so the proxied path matches prod. Unlike prod, dev still
      # publishes 8000, so anything on this host CAN spoof X-Forwarded-For and
      # hand itself a fresh rate-limit bucket. Accepted: dev is not a threat
      # model, and the alternative is dev not exercising the prod code path.
      TRUSTED_PROXY_HOSTS: ${TRUSTED_PROXY_HOSTS:-*}
```

- [ ] **Step 4: Teach Vite about the TLS proxy**

In `frontend/vite.config.ts`, after the `tailscaleHost` declaration (currently line 11):

```ts
// When the dev stack is fronted by the Caddy TLS proxy (docker-compose.yml),
// set TLS_PROXY_HOST to the hostname it serves — normally `localhost`. Vite
// then points HMR at wss://<host>:443 so the socket goes through the proxy
// instead of trying ws://localhost:5173 from an HTTPS page (which browsers
// block as mixed content). Leave unset to use the plain-HTTP dev server.
// NB: named TLS_PROXY_HOST, not HTTPS_PROXY_HOST, so no HTTP client library
// mistakes it for outbound proxy configuration.
const tlsProxyHost = process.env.TLS_PROXY_HOST
```

Add it to the host allow-list — replace the `explicitHosts` array (currently lines 26-29):

```ts
const explicitHosts = [
  ...(tailscaleHost ? [tailscaleHost] : []),
  ...(tlsProxyHost ? [tlsProxyHost] : []),
  ...rawAllowedHosts.split(',').map((h) => h.trim()).filter((h) => h && h !== '*'),
]
```

And extend the HMR branch — replace lines 50-53:

```ts
    // HMR must travel back through whichever HTTPS front-end is in play.
    // Tailscale takes precedence: if both are set, the tailnet hostname is the
    // one the browser actually loaded.
    ...(tailscaleHost
      ? { hmr: { host: tailscaleHost, protocol: 'wss', clientPort: 443 } }
      : tlsProxyHost
        ? { hmr: { host: tlsProxyHost, protocol: 'wss', clientPort: 443 } }
        : {}),
```

- [ ] **Step 5: Pass the variable through, and fix the stale API fallback**

In `docker-compose.yml`, in the `frontend` service's `environment:` block, after the `TAILSCALE_HOST` entry (currently line 43):

```yaml
      # Hostname served by the Caddy TLS proxy; points Vite HMR at wss://<host>:443.
      TLS_PROXY_HOST: ${TLS_PROXY_HOST:-}
```

Also change the `VITE_API_BASE_URL` default on line 39. It currently falls back to a hardcoded box IP:

```yaml
      VITE_API_BASE_URL: ${VITE_API_BASE_URL:-http://111.118.194.148:8000}
```

Replace with:

```yaml
      VITE_API_BASE_URL: ${VITE_API_BASE_URL:-https://api.localhost}
```

That literal IP is a leftover: with an empty `.env` the dev frontend silently calls a remote host over plain HTTP instead of the local backend — confusing on its own, and actively wrong now that the local backend is served over TLS.

- [ ] **Step 6: Verify the compose file parses**

```bash
cd /c/Users/satis/madhats-aidesign
docker compose config > /dev/null && echo "COMPOSE OK"
```

Expected: `COMPOSE OK`.

- [ ] **Step 7: Bring the dev stack up and smoke-test both hostnames**

```bash
cd /c/Users/satis/madhats-aidesign
docker compose up -d --build
sleep 15
curl -sk https://api.localhost/health
curl -sk -o /dev/null -w "frontend=%{http_code}\n" https://localhost
```

Expected: `{"status":"ok"}` and `frontend=200`. `-k` skips verification because the CA is not trusted on the host yet — that is Step 8. If `api.localhost` does not resolve, your resolver is not Chrome/Firefox; add `127.0.0.1 api.localhost` to `C:\Windows\System32\drivers\etc\hosts`.

- [ ] **Step 8: Trust the internal CA on the host**

```bash
cd /c/Users/satis/madhats-aidesign
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
```

Then import `caddy-root.crt` into **Trusted Root Certification Authorities** (PowerShell, as Administrator):

```powershell
Import-Certificate -FilePath .\caddy-root.crt -CertStoreLocation Cert:\LocalMachine\Root
```

Delete the extracted file afterwards and restart the browser. `caddy trust` alone does **not** work here — Caddy runs in a container, so the CA lives inside it, not on the host.

Verify without `-k`:

```bash
curl -s https://api.localhost/health
```

Expected: `{"status":"ok"}` with no certificate warning.

- [ ] **Step 9: Confirm HMR works over WSS**

With `TLS_PROXY_HOST=localhost` in the root `.env` (Task 4 adds it; set it now if running out of order), recreate the frontend and load `https://localhost`:

```bash
docker compose up -d --force-recreate frontend
```

Edit any string in `frontend/src/components/ChatPanel` and confirm the browser hot-reloads. In devtools, the HMR socket must be `wss://localhost/` — not `ws://localhost:5173`. A failure here shows as a console error about an insecure WebSocket from an HTTPS page.

- [ ] **Step 10: Commit**

```bash
git add caddy/Caddyfile.dev docker-compose.yml frontend/vite.config.ts
git commit -m "feat(infra): TLS for the dev stack via Caddy's internal CA

Mirrors the production proxy config so routing bugs surface locally, and
gives the microphone a secure context without Tailscale (see the note at
the top of vite.config.ts). Vite HMR is pointed at wss://<host>:443 so
the socket traverses the proxy instead of being blocked as mixed content.

local_certs is a global option, not a per-site 'tls internal', so this
file cannot reach Let's Encrypt even if a real hostname is added to it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Environment template and deployment runbook

**Files:**
- Modify: `.env.example:15-16` (VITE vars), `:42-43` (CORS note), `:55` (verify URL), plus a new TLS section
- Modify: `CLAUDE.md` §13c (the deployment runbook)

**Interfaces:**
- Consumes: `TRUSTED_PROXY_HOSTS` (Task 1), `ACME_EMAIL` (Task 2), `TLS_PROXY_HOST` (Task 3).

- [ ] **Step 1: Update `.env.example`**

Set the four URL values to their dev-with-Caddy defaults, since the dev stack now runs the proxy:

```bash
VITE_API_BASE_URL=https://api.localhost
VITE_STORE_KEY=mh_pk_madhats_local
```

```bash
EMAIL_VERIFY_BASE_URL=https://api.localhost
STUDIO_BASE_URL=https://localhost
```

Leave `ALLOWED_ORIGINS=*` **unchanged** — locking CORS is an explicit non-goal.

Append a new section:

```bash
# --- TLS / reverse proxy -----------------------------------------------------
# Caddy terminates TLS in front of both web services in each stack.
#
# Address Let's Encrypt uses for certificate-expiry notices (production only).
#
# REQUIRED for the prod stack — not optional. Caddy's `email` directive rejects
# a blank argument at parse time, so an empty value stops the proxy booting and
# takes the site down. docker-compose.prod.yml uses `${ACME_EMAIL:?...}` so you
# get a clear compose error instead of a cryptic Caddy one. Unused in dev.
ACME_EMAIL=

# Hosts whose X-Forwarded-* headers the backend trusts, for client-IP recovery.
# Rate limiting keys on the client IP, so if this is wrong every customer shares
# one bucket -- and if it is too permissive, anyone who can reach the port
# directly can rotate the header for a fresh bucket per request.
#
# LEAVE THIS BLANK. Both compose files set it themselves, next to the port
# mapping that justifies it. Only set it here if you run the backend outside
# compose behind your own proxy, and then name that proxy's IP rather than "*".
TRUSTED_PROXY_HOSTS=

# Hostname the dev Caddy serves, so Vite points HMR at wss://<host>:443.
# Leave blank to use the plain-HTTP dev server on http://localhost:5173.
TLS_PROXY_HOST=localhost

# Production values for reference (set these in the SERVER's .env):
#   VITE_API_BASE_URL=https://api.madhats.getaiconsult.com.au
#   EMAIL_VERIFY_BASE_URL=https://api.madhats.getaiconsult.com.au
#   STUDIO_BASE_URL=https://madhats.getaiconsult.com.au
#   TLS_PROXY_HOST=                     # unused in prod (static build, no HMR)
```

- [ ] **Step 2: Rewrite the CLAUDE.md §13c deploy command block**

Replace the "Recommended prod deploy" block with:

````markdown
**Prod deploy (static build + Caddy TLS):**
```bash
git pull
# project-root .env must have (prod values):
#   VITE_API_BASE_URL=https://api.madhats.getaiconsult.com.au   # baked into the bundle
#   EMAIL_VERIFY_BASE_URL=https://api.madhats.getaiconsult.com.au
#   STUDIO_BASE_URL=https://madhats.getaiconsult.com.au
#   VITE_STORE_KEY=mh_pk_madhats_local
#   ALLOWED_ORIGINS=*                    # still open; tightening is a separate change
#   ACME_EMAIL=ops@example.com
#   (TRUSTED_PROXY_HOSTS is set by docker-compose.prod.yml itself — leave it
#    blank in .env, so the trust stays coupled to the removed port mapping)
#   (+ SUPABASE_URL/keys, ADMIN_SECRET, provider keys …)
docker compose down
docker compose -f docker-compose.prod.yml up -d --build
# after ANY VITE_API_BASE_URL change, REBUILD the frontend (it's compiled in):
docker compose -f docker-compose.prod.yml up -d --build frontend
```

**Before the first deploy:** confirm `api.madhats.getaiconsult.com.au` resolves to
the box. Caddy will retry ACME against Let's Encrypt while DNS is unresolved,
which is the fastest way to hit the duplicate-certificate rate limit (5/week)
and lock yourself out of issuance for the real domain.
````

- [ ] **Step 3: Update the §13c gotchas checklist**

Add these entries:

```markdown
- **Certs vanish / re-issued every restart** → the `caddy_data` volume is missing
  or was pruned. Issued certs live in `/data`; without the volume every `up`
  re-issues and burns the Let's Encrypt duplicate limit (5/week).
- **Everyone gets 429s under mild load** → `TRUSTED_PROXY_HOSTS` is not reaching
  the backend, so `request.client.host` is Caddy's container IP and all
  customers share one rate-limit bucket. Check `docker compose exec backend env
  | grep TRUSTED`. The code default is empty (trust nothing) — the compose file
  is what opts in.
- **Re-adding `ports:` to backend or frontend in prod** re-exposes them in
  cleartext, bypassing TLS entirely — AND turns the `TRUSTED_PROXY_HOSTS: "*"`
  on that same service into a rate-limit bypass, since a direct caller could
  then rotate `X-Forwarded-For` for a fresh bucket per request. The two lines
  are deliberately adjacent; never re-add one without removing the other.
- **Mixed-content errors after deploy** → the frontend was recreated but not
  rebuilt, so the old `http://` API URL is still compiled into the bundle.
  `up -d --build frontend`.
```

- [ ] **Step 4: Update the dev-stack callout in §13**

In the "How this dev runs the stack" callout, replace the URLs with:

```
Backend → https://api.localhost, frontend → https://localhost (both via the
Caddy TLS proxy; the plain http://localhost:8000 / :5173 ports are still
published in dev for quick checks). The internal CA must be trusted once —
see docs/superpowers/plans/2026-07-25-ssl-all-servers.md Task 3 Step 8.
```

- [ ] **Step 5: Verify no stale HTTP references remain**

```bash
cd /c/Users/satis/madhats-aidesign
grep -rn "http://madhats.getaiconsult.com.au" --include="*.yml" --include="*.md" --include="*.example" . | grep -v docs/superpowers
```

Expected: no hits outside the spec/plan docs and the intentional legacy-redirect comments in `caddy/Caddyfile.prod`.

- [ ] **Step 6: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs(infra): document TLS env vars and the HTTPS deploy runbook

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Production cutover (run once, after all four tasks)

Not a code task — the deploy sequence, in the order that avoids an outage.

- [ ] **1.** Add DNS: `api.madhats` A → box public IP. Confirm with `dig +short api.madhats.getaiconsult.com.au` before continuing. ACME fails without it.
- [ ] **2.** Confirm ports 80 and 443 are free on the box: `sudo ss -lntp | grep -E ':(80|443)\b'`.
- [ ] **3.** Update the server's `.env` to the production values in Task 4 Step 2.
- [ ] **4.** `docker compose -f docker-compose.prod.yml up -d --build` — the `--build` is required, not optional, because `VITE_API_BASE_URL` is compiled into the bundle.
- [ ] **5.** Watch issuance: `docker compose -f docker-compose.prod.yml logs -f caddy` until both certificates are obtained.
- [ ] **6.** Verify:
  ```bash
  curl -sI https://madhats.getaiconsult.com.au | head -1
  curl -s  https://api.madhats.getaiconsult.com.au/health
  curl -sI http://madhats.getaiconsult.com.au | head -1          # expect 301
  curl -sI "http://madhats.getaiconsult.com.au:8000/health?x=1" | grep -i location
  ```
  The last one must show the query string preserved — that is what keeps signed email tokens valid.
- [ ] **7.** End-to-end customer run: chat → email verification link → quote link → studio resume link. This is the only check that exercises `EMAIL_VERIFY_BASE_URL`, `STUDIO_BASE_URL`, and `VITE_API_BASE_URL` together.
- [ ] **8.** Test the microphone in the studio — the secure context was the original driver.
- [ ] **9.** Devtools: no mixed-content warnings, no CORS errors.
- [ ] **10.** Confirm rate limiting is per-client, not global: from two different source IPs, exceed `RATE_LIMIT_RPM` on one and confirm the other is unaffected.

**Rollback:** `git revert` the four commits and `docker compose -f docker-compose.prod.yml up -d --build`. No schema migration, no data mutation. Legacy HTTP email links resume working immediately because the port mappings return.

**Cleanup, ~30 days out:** delete the `:8000` and `:5173` blocks from `caddy/Caddyfile.prod` and their port mappings from `docker-compose.prod.yml`, once quote tokens (`QUOTE_TOKEN_TTL_SECONDS` = 2592000) have expired.

## Known follow-ups (out of scope)

- `ALLOWED_ORIGINS` remains `*`. Tightening it needs a prior check on whether the Shopify widget issues requests from the `madhats.com.au` parent origin or only from inside the studio iframe. Still tracked in CLAUDE.md §3b.
- HSTS is not enabled. Worth adding after the legacy `:8000`/`:5173` redirects are removed — enabling it earlier would pin browsers to HTTPS while we still deliberately serve plain HTTP on those ports.
