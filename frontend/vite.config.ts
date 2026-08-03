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
      // Bind mounts don't reliably emit inotify events on Windows/macOS.
      watch: { usePolling: true },
      proxy: {
        // Same-origin API calls in dev: /api/... -> Django.
        '/api': {
          target: env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    preview: {
      host: true,
      port: 5173,
    },
  }
})
