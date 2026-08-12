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

const frontendPort = requiredPort('SSWCENTER_E2E_FRONTEND_PORT');
const outputDir = process.env.SSWCENTER_0014_PLAYWRIGHT_OUTPUT_DIR;
if (!outputDir || !isAbsolute(outputDir)) {
  throw new Error('SSWCENTER_0014_PLAYWRIGHT_OUTPUT_DIR must be an absolute private temp path');
}
const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = resolve(frontendRoot, '..');
const outputRelativeToRepo = relative(repositoryRoot, outputDir);
if (
  outputRelativeToRepo === '' ||
  (outputRelativeToRepo !== '..' &&
    !outputRelativeToRepo.startsWith(`..${sep}`) &&
    !isAbsolute(outputRelativeToRepo))
) {
  throw new Error('SSWCENTER_0014_PLAYWRIGHT_OUTPUT_DIR must remain outside the repository root');
}

export default defineConfig({
  testDir: '.',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'line',
  outputDir,
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
  // webServer is deliberately omitted.  The PowerShell owner starts/stops Vite
  // explicitly so listener and process cleanup share the same finally gate.
});
