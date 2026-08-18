import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

function requiredPort(name: string): number {
  const raw = process.env[name];
  if (raw === undefined || !/^\d+$/.test(raw)) throw new Error(`${name} must be a decimal TCP port`);
  const port = Number(raw);
  if (!Number.isSafeInteger(port) || port < 1024 || port > 65_535) {
    throw new Error(`${name} must be an unprivileged TCP port`);
  }
  return port;
}

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = resolve(frontendRoot, '..');
const cacheDir = process.env.SSWCENTER_W2_VITE_CACHE_DIR;
if (!cacheDir || !isAbsolute(cacheDir)) {
  throw new Error('SSWCENTER_W2_VITE_CACHE_DIR must be an absolute private temp path');
}
const relativeCache = relative(repositoryRoot, cacheDir);
if (
  relativeCache === ''
  || (relativeCache !== '..' && !relativeCache.startsWith(`..${sep}`) && !isAbsolute(relativeCache))
) {
  throw new Error('SSWCENTER_W2_VITE_CACHE_DIR must stay outside the repository');
}

const backendPort = requiredPort('SSWCENTER_E2E_BACKEND_PORT');
const frontendPort = requiredPort('SSWCENTER_E2E_FRONTEND_PORT');

export default defineConfig({
  root: frontendRoot,
  cacheDir,
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: frontendPort,
    strictPort: true,
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
});
