import { defineConfig, devices } from '@playwright/test';
import { RETAILER_URL } from './env';

/**
 * OrderEasy e2e journeys (OE-368). Runs only against the local/CI stack, see env.ts.
 * One worker: every test reseeds the same database.
 */
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  outputDir: 'test-results',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: RETAILER_URL,
    viewport: { width: 1440, height: 900 },
    timezoneId: 'Asia/Kolkata',
    locale: 'en-IN',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 20_000,
    navigationTimeout: 90_000,
  },
  projects: [{ name: 'chromium' }],
});
