import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.FRONTEND_BASE_URL || 'http://127.0.0.1:5173'
const headed = process.env.HEADED_UI === '1'
const slowMo = Number(process.env.PLAYWRIGHT_SLOW_MO_MS || (headed ? 300 : 0))
const triggerDemo = process.env.E2E_TRIGGER_MATMUL_DEMO === '1'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: triggerDemo ? 300_000 : 60_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
  ],
  use: {
    baseURL,
    headless: !headed,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: headed ? 'retain-on-failure' : 'off',
    launchOptions: { slowMo },
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
  },
  webServer: process.env.PLAYWRIGHT_NO_WEBSERVER === '1'
    ? undefined
    : {
        command: 'npm run dev -- --host 127.0.0.1',
        url: baseURL,
        reuseExistingServer: true,
        timeout: 60_000,
      },
  projects: [
    {
      name: process.env.PLAYWRIGHT_CHANNEL || 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
