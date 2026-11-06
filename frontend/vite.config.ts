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
      '/api': process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
    },
  },
})
