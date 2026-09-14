/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Requests to /api are forwarded to the API. By default that is the
    // FastAPI process in the local virtualenv; point VITE_API_PROXY at
    // http://localhost:8080 to use the Kind cluster instead. Development
    // only either way: the browser sees a single origin, so the backend
    // needs no CORS configuration.
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // The proxy above does not exist under test: fetch is always replaced,
    // so a test can never reach a real backend.
    css: false,
  },
})
