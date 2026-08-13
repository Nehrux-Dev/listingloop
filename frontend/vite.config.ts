import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  // Picks up VITE_* variables from the environment (docker compose injects
  // them from the root .env) as well as any local frontend/.env file.
  const env = loadEnv(mode, '.', 'VITE_')

  return {
    plugins: [react(), tailwindcss()],
    server: {
      // Listen on all interfaces so the dev server is reachable from outside
      // the container.
      host: true,
      port: 5173,
      strictPort: true,
      // Vite 6 rejects requests whose Host header it doesn't recognise (DNS
      // rebinding protection) — "localhost" passes by default, but nothing
      // reaching this container by its compose service name did. That blocks
      // exactly the kind of in-network Playwright verification this project
      // needs (see renderer/, which already runs Chromium in-network against
      // Django). Dev-only: this setting doesn't exist in a production build.
      allowedHosts: ['localhost', 'frontend'],
      // Bind mounts don't reliably emit inotify events on Windows/macOS.
      watch: { usePolling: true },
      proxy: {
        // Same-origin API calls in dev: /api/... -> Django.
        //
        // changeOrigin MUST stay false. With it on, the proxy rewrites the
        // Host header to the target ("backend:8000"), and Django builds
        // absolute media URLs from whatever Host it was given — so every
        // uploaded photo and every export came back as
        // http://backend:8000/media/..., a name only resolvable inside the
        // compose network. The browser got ERR_NAME_NOT_RESOLVED and images
        // silently failed to load.
        //
        // Left false, Django sees Host: localhost:5173 (already in
        // ALLOWED_HOSTS) and builds URLs the browser can actually fetch.
        '/api': {
          target: env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
          changeOrigin: false,
        },
        // ...and those URLs have to lead somewhere. Django serves MEDIA_ROOT
        // itself in DEBUG; without this proxy the corrected URLs would simply
        // 404 against the Vite dev server instead.
        '/media': {
          target: env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
          changeOrigin: false,
        },
      },
    },
    preview: {
      host: true,
      port: 5173,
    },
  }
})
