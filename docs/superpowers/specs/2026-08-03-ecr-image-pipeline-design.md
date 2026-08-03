# ECR image pipeline — design

**Date:** 2026-08-03
**Status:** approved, implementing

## Goal

On every push to `master`, build and push Docker images to Amazon ECR — the
backend image when `backend/` changed, the frontend image when `frontend/`
changed. Images must be **environment-agnostic**: configuration is injected at
container start, not compiled in at build time.

## Why the frontend needs work first

Vite inlines every `VITE_*` variable into the JS bundle when `vite build` runs.
A frontend image built today is permanently locked to whichever API URL CI
passed, which makes "build once, deploy anywhere" impossible and would force CI
to build a separate image per environment.

The fix is a **sentinel substitution** at container start:

- the build bakes the literal strings `__RUNTIME_API_BASE_URL__` and
  `__RUNTIME_STORE_KEY__` into the bundle;
- `frontend/docker-entrypoint.sh` replaces them from the container's environment
  before handing off to `serve`.

No application source changes — `src/lib/api.ts` and `src/admin/adminApi.ts`
keep reading `import.meta.env` exactly as they do now, so dev, tests and the
Vite dev-server image (`Dockerfile.dev`) are all untouched.

### The bundle is rebuilt from a pristine copy on every start

The build stage stores the bundle at `/app/dist-template`; the entrypoint copies
it to `/app/dist` fresh on **every** start, then substitutes. This makes the
entrypoint idempotent — substitution always runs against known-clean input.

In-place substitution would be one-shot: after the first start no sentinel
remains, so a restart could never *repair* anything. A first start interrupted
part-way through `sed` (OOM kill, host reboot mid-write) would leave a
half-substituted bundle that every later restart serves, forever, with no error
anywhere.

It does **not** protect against a stale URL after an env change, and an earlier
draft of this design wrongly claimed it did. Docker fixes a container's
environment at *creation*: `docker restart` — and `docker compose restart`,
which does not re-read `.env` — always reuse the original value. Changing
`VITE_API_BASE_URL` requires a new container (`up -d --force-recreate frontend`),
exactly as changing a backend env var already does (CLAUDE.md §13).

### Failure modes

- `VITE_API_BASE_URL` unset → the container **aborts at start** with an
  explanatory message. It never falls back to `http://localhost:8000`, which
  would present as a total outage that looks like a backend fault.
- `VITE_STORE_KEY` unset → treated as empty, matching the app's own `?? ''`
  fallback. This is legitimate and must not abort.

## Change detection

Two workflow files using GitHub's native `on.push.paths`, rather than one
workflow with a third-party paths-filter action:

| Workflow | Triggers on |
|---|---|
| `.github/workflows/backend-image.yml` | `backend/**`, its own workflow file |
| `.github/workflows/frontend-image.yml` | `frontend/**`, its own workflow file |

Both also expose `workflow_dispatch` so an image can be rebuilt without a code
change. Trade-off accepted: some YAML duplication, in exchange for no
third-party action and two independently readable checks in the GitHub UI.

## Workflow shape (identical per service)

1. `actions/checkout@v4`
2. `aws-actions/configure-aws-credentials@v4` — access key + secret from repo
   secrets, region from a repo variable
3. `aws-actions/amazon-ecr-login@v2` — its `registry` output supplies the
   registry host, so no AWS account ID is stored anywhere
4. `docker/setup-buildx-action@v3`
5. `docker/build-push-action@v6` — `context: ./backend` (or `./frontend`),
   tags `:<git-sha>` and `:latest`, GitHub Actions layer cache scoped per service

Pushes are **unconditional** — no test gate. Test suites remain a local step.

The frontend build passes **no build arguments and needs no secrets**, which is
the direct payoff of moving configuration to runtime.

## Tagging

`:<git-sha>` (immutable, the thing to roll back to) plus a moving `:latest`
(the thing the box pulls).

## Configuration to create

| Kind | Name |
|---|---|
| Secret | `AWS_ACCESS_KEY_ID` |
| Secret | `AWS_SECRET_ACCESS_KEY` |
| Variable | `AWS_REGION` |
| Variable | `ECR_BACKEND_REPOSITORY` |
| Variable | `ECR_FRONTEND_REPOSITORY` |

Plus, in AWS: two ECR repositories (ECR does not create them on push) and an
IAM user whose policy is scoped to ECR push only.

## Files

| Action | Path |
|---|---|
| new | `.github/workflows/backend-image.yml` |
| new | `.github/workflows/frontend-image.yml` |
| new | `frontend/docker-entrypoint.sh` |
| edit | `frontend/Dockerfile` — sentinel ARGs, `dist-template`, entrypoint |
| edit | `docker-compose.prod.yml` — frontend drops its build args |
| edit | `CLAUDE.md` §13c — the "API URL is a BUILD-TIME value" rule is no longer true |
| delete | `.github/workflows/docker-image.yml` |

`.github/workflows/docker-image.yml` is the untouched GitHub scaffold. It builds
`./Dockerfile` at the repository root, which does not exist, so it fails on
every push to master today.

## Out of scope

The pipeline pushes to ECR and stops. Nothing connects to the production box or
pulls the new image, and `docker-compose.prod.yml` continues to build locally.
Switching prod to `image:` pulls is a separate change.
