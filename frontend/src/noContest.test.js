import { describe, expect, it } from 'vitest'

// The live site never names a contest: no SIH, Smart India Hackathon or
// hackathon in any page or component. The repository's README and docs may.
const sources = import.meta.glob(['./**/*.{js,jsx}', '!./**/*.test.{js,jsx}', '!./test/**'],
  { query: '?raw', import: 'default', eager: true })

describe('the website names no contest', () => {
  it('scans the whole source tree', () => {
    expect(Object.keys(sources)).toContain('./routes/Citizen.jsx')
  })

  it.each(Object.entries(sources))('%s says nothing of a hackathon', (_, text) => {
    expect(text).not.toMatch(/\bSIH\b|smart\s+india|hackathon/i)
  })
})
