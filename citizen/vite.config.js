import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The citizen site: static pages, deployed on its own (vercel.json). It shares
// no code with frontend/ and has no API yet.
export default defineConfig({
  plugins: [react()],
  build: {
    // The content policy allows fonts only from this site (font-src 'self'),
    // so fonts are always emitted as files, never inlined as data: URLs.
    assetsInlineLimit: (file) => (/\.(woff2?|ttf|otf)$/.test(file) ? false : undefined),
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.js',
    include: ['src/**/*.test.{js,jsx}'],
  },
})
