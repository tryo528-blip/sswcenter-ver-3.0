import { defineConfig, devices } from 'playwright/test';

function readLocalPort(name: string, fallback: number): number {
  const rawValue = process.env[name];
  if (rawValue === undefined) return fallback;
  if (!/^\d+$/.test(rawValue)) {
    throw new Error(`${name} must be a decimal TCP port`);
  }
  const port = Number(rawValue);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${name} must be between 1 and 65535`);
  }
  return port;
}

const frontendPort = readLocalPort('SSWCENTER_E2E_FRONTEND_PORT', 4173);
const frontendBaseUrl = `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  // W1A shares one PostgreSQL database across viewport projects.
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: frontendBaseUrl,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium-1440x1000',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 1000 },
      },
    },
    {
      name: 'chromium-1440x900',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: 'chromium-1366x768',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1366, height: 768 },
      },
    },
  ],
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort} --strictPort`,
    url: frontendBaseUrl,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
