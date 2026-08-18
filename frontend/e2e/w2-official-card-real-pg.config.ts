import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from 'playwright/test';

function requiredPort(name: string): number {
  const raw = process.env[name];
  if (raw === undefined || !/^\d+$/.test(raw)) throw new Error(`${name} must be a decimal TCP port`);
  const port = Number(raw);
  if (!Number.isSafeInteger(port) || port < 1024 || port > 65_535) {
    throw new Error(`${name} must be an unprivileged TCP port`);
  }
  return port;
}

function privateOutputDirectory(): string {
  const outputDir = process.env.SSWCENTER_W2_PLAYWRIGHT_OUTPUT_DIR;
  if (!outputDir || !isAbsolute(outputDir)) {
    throw new Error('SSWCENTER_W2_PLAYWRIGHT_OUTPUT_DIR must be an absolute private temp path');
  }
  const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  const repositoryRoot = resolve(frontendRoot, '..');
  const relativePath = relative(repositoryRoot, outputDir);
  if (
    relativePath === ''
    || (relativePath !== '..' && !relativePath.startsWith(`..${sep}`) && !isAbsolute(relativePath))
  ) {
    throw new Error('SSWCENTER_W2_PLAYWRIGHT_OUTPUT_DIR must stay outside the repository');
  }
  return outputDir;
}

const frontendPort = requiredPort('SSWCENTER_E2E_FRONTEND_PORT');

export default defineConfig({
  testDir: '.',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'line',
  outputDir: privateOutputDirectory(),
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    screenshot: 'off',
    trace: 'off',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium-1440x1000',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 1000 },
      },
    },
  ],
  // The PowerShell owner starts and stops both FastAPI and Vite so cleanup is
  // checked in the same finally block as PostgreSQL.
});
