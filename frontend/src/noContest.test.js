import { describe, expect, it } from 'vitest'
import indexHtml from '../index.html?raw'
import robots from '../public/robots.txt?raw'

// The live site never names a contest: no SIH, Smart India Hackathon or
// hackathon in any page, component, stylesheet, data file or public text
// file (the README and docs may). "SIH" counts with a number after it, as
// in SIH26183.
const CONTEST = /\bSIH(?![a-z])|hackathon|smart\s*india/i
const sources = import.meta.glob(['./**/*.{js,jsx,css,json}', '!./**/*.test.{js,jsx}', '!./test/**'],
  { query: '?raw', import: 'default', eager: true })
const shipped = [['index.html', indexHtml], ['public/robots.txt', robots], ...Object.entries(sources)]

describe('what the site says', () => {
  it('reads the forms a contest name has taken', () => {
    for (const name of ['SIH', 'SIH26183', 'SIH2025', 'Smart India Hackathon', 'SmartIndia', 'a hackathon']) {
      expect(name).toMatch(CONTEST)
    }
    expect('SIHgh, a sigh, Sihanouk, CSS ships').not.toMatch(CONTEST)
  })

  it('covers the stylesheets and data as well as the code', () => {
    expect(shipped.some(([path]) => path.endsWith('.css'))).toBe(true)
    expect(shipped.some(([path]) => path.endsWith('.json'))).toBe(true)
    expect(Object.keys(sources)).toContain('./routes/Citizen.jsx')
  })

  it.each(shipped)('%s never names a contest', (_, text) => {
    expect(text).not.toMatch(CONTEST)
  })
})
