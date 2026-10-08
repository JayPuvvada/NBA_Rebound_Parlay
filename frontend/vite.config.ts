import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from "path"

const backend = process.env.NBA_BACKEND_URL || 'http://127.0.0.1:5001'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    proxy: {
      '/generate-picks': backend,
      '/markets': backend,
      '/player-history': backend,
      '/games': backend,
      '/predict': backend,
      '/cheat-sheet': backend,
      '/preseason-roster': backend,
      '/preseason-player': backend,
      '/preseason-markets': backend,
    }
  }
})
