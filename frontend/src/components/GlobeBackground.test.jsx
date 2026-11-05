import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import GlobeBackground, { placeGlobe } from './GlobeBackground'

describe('GlobeBackground', () => {
  it('draws on a decorative canvas that screen readers skip', () => {
    render(<GlobeBackground />)
    const canvas = screen.getByTestId('globe-bg')
    expect(canvas.tagName).toBe('CANVAS')
    expect(canvas).toHaveAttribute('aria-hidden', 'true')
    // No tooltip until an exchange is hovered.
    expect(document.querySelector('.globe-tip')).toBeNull()
  })

  it('sits half off the right edge on a desk and further out on a phone', () => {
    const desk = placeGlobe(1440, 900)
    expect(desk.R).toBeCloseTo(612)
    expect(desk.cx).toBeCloseTo(1440 - 612 * 0.48)
    expect(desk.cx + desk.R).toBeGreaterThan(1440)
    const phone = placeGlobe(400, 844)
    expect(phone.R).toBeCloseTo(300)
    expect(phone.cx).toBeCloseTo(400 - 300 * 0.25)
  })
})
