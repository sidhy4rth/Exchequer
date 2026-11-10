import { defineConfig } from '@playwright/test'

// The accessibility check (e2e/a11y.spec.js): axe opens every page of a
// running Exchequer in both themes, at a desktop and a phone size, and fails
// on any WCAG 2.2 AA violation. It never has a default site, so it cannot
// open the live one by accident: build the frontend for the backend to serve
// (VITE_API_BASE= npm run build, as CI does), serve it on a free port, then
//   EXCHEQUER_URL=http://127.0.0.1:8000 npm run a11y
// A11Y_BROWSER runs it in a Chromium-based browser already installed
// (Chrome, Brave, Edge) instead of the one `npx playwright install` fetches.
const site = process.env.EXCHEQUER_URL
if (!site) throw new Error('Set EXCHEQUER_URL to a running Exchequer, e.g. EXCHEQUER_URL=http://127.0.0.1:8000 npm run a11y')

export default defineConfig({
  testDir: './e2e',
  testMatch: 'a11y.spec.js',
  timeout: 60_000,
  reporter: [['list']],
  use: {
    baseURL: site,
    launchOptions: process.env.A11Y_BROWSER ? { executablePath: process.env.A11Y_BROWSER } : {},
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1280, height: 900 } } },
    { name: 'phone', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
    // Between the two, where a wide table must scroll rather than be cut off:
    // only the pages that ask for it (`tablet` in a11y.pages.js).
    { name: 'tablet', use: { viewport: { width: 1024, height: 768 } } },
  ],
})
