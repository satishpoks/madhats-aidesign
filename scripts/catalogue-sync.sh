#!/bin/sh
# Catalogue fetch arm. Runs in an ALPINE curl container — NOT in the backend.
#
# Shopify's Cloudflare edge refuses the backend container's HTTP client from a
# hosting ASN but accepts this image's curl, from the same droplet and the same
# IP. Measured on the staging droplet 2026-07-29, back to back:
#
#     backend  container, 6 requests, no delay -> 429 429 429 429 429 429
#     watchdog container, 6 requests, no delay -> 200 200 200 200 200 200
#
# Not rate limiting (the burst above passes), not the User-Agent, not the
# flags — bare `curl <url>` is refused from the backend too. So this script
# exists purely because it runs somewhere the backend cannot reach from.
#
# It carries no schedule of its own: this image has no tzdata, so it cannot
# know when midnight Sydney is. The backend decides who is due; we poll and
# fetch. Every parsed response is plain text because busybox has no jq.
set -u

API="${API_BASE:-http://backend:8000}"
POLL_SECONDS="${POLL_SECONDS:-30}"
PAGE_LIMIT=250
MAX_PAGES=10

log() { echo "[catalogue-sync] $*"; }

# curl against our own API — internal, so no fingerprint concerns here.
api() {
    method=$1
    path=$2
    shift 2
    curl -fsS -X "$method" -H "X-Admin-Secret: ${ADMIN_SECRET}" "$API$path" "$@"
}

# Fetch every page of one store's feed and hand it to the backend. Pages are
# buffered server-side; nothing touches the live catalogue until commit, so
# returning early here is always safe.
sync_store() {
    store=$1
    base=$2
    page=1

    log "store $store <- $base"
    while [ "$page" -le "$MAX_PAGES" ]; do
        body=$(curl -fsS --compressed -m 120 \
            "$base/products.json?limit=$PAGE_LIMIT&page=$page") || {
            log "  page $page: fetch FAILED — abandoning, catalogue untouched"
            api POST "/admin/stores/$store/catalogue/abandon" >/dev/null 2>&1 || true
            return 1
        }

        count=$(printf '%s' "$body" | api POST \
            "/admin/stores/$store/catalogue/pages/$page" \
            -H "Content-Type: application/json" --data-binary @-) || {
            log "  page $page: ingest FAILED — abandoning"
            api POST "/admin/stores/$store/catalogue/abandon" >/dev/null 2>&1 || true
            return 1
        }

        case "$count" in ''|*[!0-9]*) count=0 ;; esac
        log "  page $page: $count products"
        [ "$count" -lt "$PAGE_LIMIT" ] && break

        page=$((page + 1))
        sleep 2          # be a polite client; the feed is ~2 MB a page
    done

    if api POST "/admin/stores/$store/catalogue/commit" >/dev/null; then
        log "  committed"
    else
        log "  commit FAILED — catalogue left as it was"
        return 1
    fi
}

log "polling $API every ${POLL_SECONDS}s"
while true; do
    if api GET /admin/catalogue/sync-targets > /tmp/targets 2>/dev/null; then
        # Redirect, not a pipe: a `while read` on the right of a pipe runs in a
        # subshell in POSIX sh, and we would lose everything it sets.
        #
        # The `|| [ -n "$store" ]` is load-bearing. `read` returns non-zero at
        # EOF when the final line has no trailing newline, which drops that
        # line entirely — with one store queued that means syncing NOTHING,
        # silently. The endpoint terminates every line, and this handles it
        # anyway; belt and braces, because the failure is invisible.
        while read -r store base || [ -n "${store:-}" ]; do
            [ -n "${store:-}" ] || continue
            sync_store "$store" "$base" || log "store $store: run failed"
        done < /tmp/targets
    fi
    sleep "$POLL_SECONDS"
done
