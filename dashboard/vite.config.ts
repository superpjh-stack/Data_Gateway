/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const API = process.env.TWIN_API ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': API,
      '/ws': { target: API.replace('http', 'ws'), ws: true },
    },
  },
  build: { chunkSizeWarningLimit: 1500 },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.{ts,tsx}'],
    setupFiles: ['tests/setup.ts'],
  },
})
