/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// When the dev server is fronted by `tailscale serve` (HTTPS reverse proxy),
// set TAILSCALE_HOST to the MagicDNS name (e.g. minipc-owkhu.tail888169.ts.net).
// This lets Vite accept that Host header and makes HMR connect back over WSS:443
// through the proxy. Serving over HTTPS is what unblocks the microphone / Web
// Speech API (a secure context is required — plain-HTTP LAN IPs never qualify).
// Leave it unset for the normal localhost/docker flow.
const tailscaleHost = process.env.TAILSCALE_HOST

// When the dev stack is fronted by the Caddy TLS proxy (docker-compose.yml),
// set TLS_PROXY_HOST to the hostname it serves — normally `localhost`. Vite
// then points HMR at wss://<host>:443 so the socket goes through the proxy
// instead of trying ws://localhost:5173 from an HTTPS page (which browsers
// block as mixed content). Leave unset to use the plain-HTTP dev server.
// NB: named TLS_PROXY_HOST, not HTTPS_PROXY_HOST, so no HTTP client library
// mistakes it for outbound proxy configuration.
const tlsProxyHost = process.env.TLS_PROXY_HOST

// Which hostnames the dev server accepts in its Host-header check, via the
// ALLOWED_HOSTS env var (relaxes only the host check; does NOT touch HMR):
//   ALLOWED_HOSTS=*                              → accept ANY host (use when the
//                                                  dev stack sits behind your own
//                                                  reverse proxy / public domain)
//   ALLOWED_HOSTS=host.a.com,host.b.com          → accept exactly those hosts
//   (unset)                                      → Vite default (localhost/IP only)
// Not needed for the production static build (`frontend/Dockerfile` serves static
// files with no host checking at all).
const rawAllowedHosts = (process.env.ALLOWED_HOSTS ?? '').trim()
const allowAnyHost = ['*', 'all', 'true'].includes(rawAllowedHosts.toLowerCase())
const explicitHosts = [
  ...(tailscaleHost ? [tailscaleHost] : []),
  ...(tlsProxyHost ? [tlsProxyHost] : []),
  ...rawAllowedHosts.split(',').map((h) => h.trim()).filter((h) => h && h !== '*'),
]

// Vite's server.allowedHosts accepts `true` (any host) or a string[] allow-list.
const allowedHosts: true | string[] | undefined = allowAnyHost
  ? true
  : explicitHosts.length
    ? explicitHosts
    : undefined

export default defineConfig({
  plugins: [react()],
  // Load env from the REPO ROOT (one level up), not frontend/, so there is a
  // single source of truth shared with the backend + docker-compose. Vite only
  // ever inlines VITE_-prefixed vars into the client bundle — the root .env's
  // backend secrets are visible to this config process but never emitted to the
  // browser. Rule that keeps that true: never name a real secret VITE_*.
  envDir: '..',
  server: {
    port: 5173,
    host: true,
    ...(allowedHosts !== undefined ? { allowedHosts } : {}),
    // HMR must travel back through whichever HTTPS front-end is in play.
    // Tailscale takes precedence: if both are set, the tailnet hostname is the
    // one the browser actually loaded.
    ...(tailscaleHost
      ? { hmr: { host: tailscaleHost, protocol: 'wss', clientPort: 443 } }
      : tlsProxyHost
        ? { hmr: { host: tlsProxyHost, protocol: 'wss', clientPort: 443 } }
        : {}),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
  },
})
