import { defineConfig } from '@playwright/test'

// Browser checks of a running Exchequer, by default the live one. Read-only:
// they open pages and a stored case, and never start a trace, so running them
// adds nothing to the case store. Point them elsewhere with
// EXCHEQUER_URL=http://localhost:8000 npm run canary.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.EXCHEQUER_URL ?? 'https://exchequer-production.up.railway.app',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
})
