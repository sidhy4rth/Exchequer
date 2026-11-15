import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  fetchChains: () => Promise.resolve({ chains: {
    ethereum: { risk_labels: { sanctioned: 60000, poisoning: 27600000 } },
    bsc: { risk_labels: { poisoning: 20900000 } },
  } }),
}))

const { default: ExchangeGlobe } = await import('./ExchangeGlobe')

// jsdom has no canvas: a 2-D context whose every call does nothing and hands
// back the context (a gradient, image data), blank.
const noop = () => {}
const context = new Proxy({}, {
  get: (_, key) => (key === 'data' ? new Uint8ClampedArray(4) : key === 'width' ? 0 : () => context),
  set: () => true,
})

describe('the front door headline', () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('says it counts an address once per chain, to the two decimals of the chain rows', async () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
    vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: noop, removeEventListener: noop }))
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => context)
    render(<ExchangeGlobe open={false} onOpen={noop} />)
    const term = await screen.findByText('Flagged addresses screened, live, counted once per chain')
    expect(term.nextElementSibling).toHaveTextContent(/^48\.56M$/)
    expect(screen.getByText('27.66M')).toBeInTheDocument()
    expect(screen.getByText('20.90M')).toBeInTheDocument()
  })
})
