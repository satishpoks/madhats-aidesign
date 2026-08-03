#!/bin/sh
# Runtime configuration for the static frontend bundle.
#
# WHY THIS EXISTS: Vite inlines every VITE_* variable into the JS at BUILD time,
# so a built image is normally locked to whichever API URL `vite build` saw. To
# keep ONE image deployable to any environment (which is what makes pushing to
# ECR worthwhile), the build bakes placeholder sentinels instead of real values
# and this script substitutes them from the container's environment at START.
#
# The application source is untouched by all this — src/lib/api.ts and
# src/admin/adminApi.ts still just read import.meta.env, so dev, the test suite
# and Dockerfile.dev (the HMR dev server) behave exactly as before.
set -eu

: "${VITE_API_BASE_URL:?is required - it is the public URL the BROWSER calls, e.g. https://api.madhats.getaiconsult.com.au. Refusing to start: falling back to localhost here would produce a total outage that presents as a backend fault.}"

# Empty is legitimate — it matches the app's own `?? ''` fallback — so this one
# gets no `:?` guard.
VITE_STORE_KEY="${VITE_STORE_KEY:-}"

# Rebuild the served directory from the pristine copy on EVERY start, so this
# script is idempotent: substitution always runs against known-clean input.
#
# In-place substitution would be a one-shot operation — after the first start no
# sentinel remains — which makes a restart unable to REPAIR anything. If a first
# start is interrupted part-way through `sed` (OOM kill, host reboot mid-write),
# the half-substituted bundle is what every subsequent restart would serve,
# forever, with no error anywhere. Copying costs milliseconds and removes that.
#
# NOTE it does NOT protect against a stale URL after an env change: Docker fixes
# a container's environment at CREATION, so `docker restart` (and `docker
# compose restart`, which does not re-read .env) always reuse the original
# value. Changing VITE_API_BASE_URL requires a new container —
# `docker compose -f docker-compose.prod.yml up -d --force-recreate frontend`.
rm -rf /app/dist
cp -a /app/dist-template /app/dist

# `|` as the sed delimiter because the values are URLs and contain `/`.
# `-r` so an unexpectedly empty file list is a no-op rather than a sed usage
# error (`set -e` would abort the container).
find /app/dist -type f \( -name '*.js' -o -name '*.css' -o -name '*.html' -o -name '*.map' \) -print0 \
  | xargs -0 -r sed -i \
      -e "s|__RUNTIME_API_BASE_URL__|${VITE_API_BASE_URL}|g" \
      -e "s|__RUNTIME_STORE_KEY__|${VITE_STORE_KEY}|g"

# Log the resolved URL: a wrong-but-set value is the likeliest failure now, and
# this is the cheapest way to catch it. Not a secret — it is a public URL that
# is visible in the bundle and in every browser network tab.
echo "frontend: serving with VITE_API_BASE_URL=${VITE_API_BASE_URL}"

exec "$@"
