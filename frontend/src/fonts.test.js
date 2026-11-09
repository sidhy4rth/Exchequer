import { describe, expect, it } from 'vitest'
import indexHtml from '../index.html?raw'

// R27: the page loads its fonts from this server. A request to Google on
// every visit would tell Google who opened a police tracing tool, and fail
// on networks that block outside hosts.
describe('fonts are served from this site', () => {
  const sources = import.meta.glob(['./**/*.{js,jsx,css}', '!./**/*.test.{js,jsx}'],
    { query: '?raw', import: 'default', eager: true })

  it('index.html loads nothing from Google', () => {
    expect(indexHtml).not.toMatch(/googleapis|gstatic/)
  })

  it.each(Object.entries(sources))('%s loads nothing from Google', (_, text) => {
    expect(text).not.toMatch(/googleapis|gstatic/)
  })

  it('the app imports every weight the stylesheet uses', () => {
    const main = sources['./main.jsx']
    for (const face of ['sans/300', 'sans/400', 'sans/500', 'sans/600', 'mono/400', 'mono/500', 'mono/600', 'serif/500', 'serif/600']) {
      expect(main).toContain(`@fontsource/ibm-plex-${face}.css`)
    }
  })
})
