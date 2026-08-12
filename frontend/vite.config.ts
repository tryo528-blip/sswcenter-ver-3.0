import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

function readLocalPort(name: string, fallback: number): number {
  const rawValue = process.env[name]
  if (rawValue === undefined) return fallback
  if (!/^\d+$/.test(rawValue)) {
    throw new Error(`${name} must be a decimal TCP port`)
  }
  const port = Number(rawValue)
  if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${name} must be between 1 and 65535`)
  }
  return port
}

const backendPort = readLocalPort('SSWCENTER_E2E_BACKEND_PORT', 8000)

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: false,
      },
      '/health': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: false,
      },
    },
  },
})
