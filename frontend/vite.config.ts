import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from "path"

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      '/games': 'http://127.0.0.1:5001',
      '/predict': 'http://127.0.0.1:5001',
      '/cheat-sheet': 'http://127.0.0.1:5001',
    }
  }
})
