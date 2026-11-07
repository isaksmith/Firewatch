import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  // No prefix on purpose: API_TOKEN is read here on the server side and must never be a VITE_ variable,
  // because Vite inlines those into the browser bundle.
  const env = loadEnv(mode, '..', '')
  return {
    plugins: [react(), tailwindcss()],
    optimizeDeps: {
      // maplibre-gl v6 loads its worker relative to its own module; pre-bundling breaks that URL.
      exclude: ['maplibre-gl'],
    },
    server: {
      proxy: {
        '/api': {
          // 127.0.0.1 rather than localhost: localhost can resolve to IPv6 and hit another service on :8000.
          target: env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
          headers: env.API_TOKEN ? { 'X-Firewatch-Token': env.API_TOKEN } : {},
        },
      },
    },
  }
})
