import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import { stubFetch } from './test/setup'

// The globe is WebGL; jsdom has none. What is tested is who gets through which door.
vi.mock('./components/ExchangeGlobe', () => ({
  default: ({ onOpen, hint }) => <div data-testid="globe" onClick={onOpen}>{hint}</div>,
}))

const health = { status: 'ok', default_chain: 'ethereum', chains: {} }

function at(path) {
  stubFetch({ '/health': { body: health }, '/cases': { body: { count: 0, cases: [] } } })
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
}

describe('the demo doors', () => {
  it('sends a fresh tab to the investigator sign-in', async () => {
    at('/')
    expect(await screen.findByRole('button', { name: /open investigator sign-in/i })).toBeInTheDocument()
  })

  it('returns an officer to the trace they asked for after signing in', async () => {
    const user = userEvent.setup()
    at('/case/abc123')
    await user.click(await screen.findByText(/click anywhere to log in/i))
    await user.click(screen.getByRole('button', { name: /open the console/i }))
    // TraceView asks for the stored case it was sent to, not the home page.
    await vi.waitFor(() =>
      expect(fetch.mock.calls.some(([url]) => String(url).includes('/trace/abc123'))).toBe(true))
  })

  it('shakes off a wrong access code', async () => {
    const user = userEvent.setup()
    at('/signin/investigator')
    await user.click(await screen.findByText(/click anywhere to log in/i))
    const code = screen.getByLabelText(/access code/i)
    await user.clear(code)
    await user.type(code, 'wrong')
    await user.click(screen.getByRole('button', { name: /open the console/i }))
    expect(screen.getByText('Not recognised.')).toBeInTheDocument()
    expect(code).toHaveAttribute('aria-invalid', 'true')
  })

  it('keeps a citizen out of the investigator console', async () => {
    sessionStorage.setItem('exchequer-demo-session', 'citizen')
    at('/')
    // The citizen page renders; the console's address field never does.
    expect(await screen.findByRole('button', { name: 'Sign out' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Reported wallet address')).not.toBeInTheDocument()
  })
})
