import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: {
    // maplibre-gl v6 loads its worker relative to its own module; pre-bundling breaks that URL.
    exclude: ['maplibre-gl'],
  },
  server: {
    proxy: {
      // 127.0.0.1 rather than localhost: localhost can resolve to IPv6 and hit another service on :8000.
      // The API token stays on the server side: the proxy adds it, so it is never in the browser bundle.
      // Use API_TOKEN (not a VITE_ variable, which Vite would ship to the page).
      '/api': {
        target: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        headers: process.env.API_TOKEN ? { 'X-Firewatch-Token': process.env.API_TOKEN } : {},
      },
      '/lite': process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
    },
  },
})
