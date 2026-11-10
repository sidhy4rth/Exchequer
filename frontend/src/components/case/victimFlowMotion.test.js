import { describe, expect, it } from 'vitest'
import { countFrames, particleRoutes, stagger } from './victimFlowMotion'
import { victimFlowLayout } from './victimFlowLayout'
import flow from '../../test/victim-flow-11.json'
import recordings from '../../../../backend/data/recorded_demos.json'

// The Flow tab's motion, worked out without drawing it: the frames of a
// figure that counts up, and the routes of the slow lights on the Sankey.
const demo = recordings.find((r) => r.demo === 11).result
const lay = victimFlowLayout(flow, { graph: demo.graph, height: 420 })

describe('a figure that counts up', () => {
  it('runs from zero to the very text the page shows, keeping its decimals, grouping and words', () => {
    const f = countFrames('8,732.34')
    expect(f(0)).toBe('0.00')
    expect(f(0.5)).toBe('4,366.17')
    expect(f(1)).toBe('8,732.34')
    expect(countFrames('6.4%')(0.5)).toBe('3.2%')
    expect(countFrames('9,891')(0.5)).toBe('4,946')
    expect(countFrames('0.00012')(1)).toBe('0.00012')
  })

  it('does not count what is not a plain figure', () => {
    expect(countFrames('0%')).toBeNull()
    expect(countFrames('under 0.1%')).toBeNull()
    expect(countFrames('')).toBeNull()
    expect(countFrames(undefined)).toBeNull()
  })
})

describe('the stagger', () => {
  it('is 60 ms a step, capped at eight steps', () => {
    expect([0, 1, 7, 8, 30].map((i) => stagger(i, 300))).toEqual([300, 360, 720, 720, 720])
    expect(stagger(2, 1700, 300)).toBe(2300)
  })
})

describe('the lights on the ribbons', () => {
  const lights = particleRoutes(lay)

  it('are few, green only on the way to an exchange, the rest neutral', () => {
    expect(lights.length).toBeGreaterThan(0)
    expect(lights.length).toBeLessThanOrEqual(5)
    expect(lights.filter((l) => l.colour === 'go').map((l) => l.kind)).toEqual(['exchange', 'exchange', 'exchange'])
    for (const l of lights.filter((x) => x.colour !== 'go')) {
      expect(l.colour).toBe('grey')
      expect(['exchange', 'instant_exchanger']).not.toContain(l.kind)
    }
  })

  it('ride the middle of the ribbons they follow', () => {
    const pairs = []
    for (let j = 0; j < lay.ribbons.length; j += 2) pairs.push([lay.ribbons[j], lay.ribbons[j + 1]])
    const near = (u, v) => Math.abs(u - v) < 0.01
    for (const l of lights) {
      const on = pairs.find(([a, b]) => b.kind === l.kind && near((a.sy0 + a.sy1) / 2, l.y[0]) && near((b.ty0 + b.ty1) / 2, l.y[2]))
      expect(on).toBeTruthy()
      const [a, b] = on
      expect(near((a.ty0 + a.ty1) / 2, l.y[1])).toBe(true)
      expect(near((b.sy0 + b.sy1) / 2, l.y[1])).toBe(true)
      expect(l.x.map((x) => +x.toFixed(1))).toEqual([a.x0, a.x1, b.x1].map((x) => +((x / lay.width) * 100).toFixed(1)))
    }
  })

  it('start after the ribbons are drawn, spread evenly over one slow trip', () => {
    expect(lights[0].delay).toBe(2.2)
    const steps = lights.slice(1).map((l, i) => +(l.delay - lights[i].delay).toFixed(3))
    expect(new Set(steps).size).toBe(1)
    expect(steps[0] * lights.length).toBeCloseTo(4.8)
  })

  it('never exceed the number asked for, and need a layout', () => {
    expect(particleRoutes(lay, { max: 2 })).toHaveLength(2)
    expect(particleRoutes(null)).toEqual([])
    expect(particleRoutes({ ribbons: [] })).toEqual([])
  })
})
