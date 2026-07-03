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

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    ...(tailscaleHost
      ? {
          allowedHosts: [tailscaleHost],
          hmr: { host: tailscaleHost, protocol: 'wss', clientPort: 443 },
        }
      : {}),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
  },
})
