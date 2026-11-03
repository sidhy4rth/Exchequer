import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    // Vite inlines small assets as data: URLs. The content policy allows
    // fonts only from this site (font-src 'self', security_headers.py), so
    // an inlined font would be blocked in production: always emit fonts as files.
    assetsInlineLimit: (file) => (/\.(woff2?|ttf|otf)$/.test(file) ? false : undefined),
  },
  server: {
    port: 5173,
    // Proxy API calls to the FastAPI backend so the frontend can use relative
    // URLs in development and never needs the backend's origin hardcoded.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  // Component tests run in jsdom. The canvas-heavy views (globe, graph) are
  // stubbed per test; what is tested here is the logic around them.
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.js',
    // e2e/ is Playwright's (npm run canary), against a running site.
    include: ['src/**/*.test.{js,jsx}'],
  },
})
