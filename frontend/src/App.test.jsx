import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import { stubFetch } from './test/setup'
import recordings from '../../backend/data/recorded_demos.json'

// The globe is WebGL; jsdom has none. What is tested is who gets through which door.
vi.mock('./components/ExchangeGlobe', () => ({
  default: ({ onOpen, hint }) => <div data-testid="globe" onClick={onOpen}>{hint}</div>,
}))

const health = { status: 'ok', default_chain: 'ethereum', chains: {} }

function at(path) {
  stubFetch({ '/chains': { body: health }, '/cases': { body: { count: 0, cases: [] } } })
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
}

describe('the demo doors', () => {
  it('sends a fresh tab to the investigator door', async () => {
    at('/')
    expect(await screen.findByRole('button', { name: /enter as investigator/i })).toBeInTheDocument()
  })

  it('returns an officer to the trace they asked for after entering', async () => {
    const user = userEvent.setup()
    at('/case/abc123')
    await user.click(await screen.findByText(/click anywhere to enter/i))
    await user.click(screen.getByRole('button', { name: /open the console/i }))
    // TraceView asks for the stored case it was sent to, not the home page.
    await vi.waitFor(() =>
      expect(fetch.mock.calls.some(([url]) => String(url).includes('/trace/abc123'))).toBe(true))
  })

  it('opens a recorded demo from the recording, never by tracing', async () => {
    const user = userEvent.setup()
    const recorded = recordings.find((r) => r.demo === 9)
    // The graph sizes itself with ResizeObserver, which jsdom lacks.
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
    stubFetch({ '/chains': { body: health }, '/demos/recorded/9': { body: { ...recorded.result, case_id: null, created_at: recorded.recorded_at, recorded_demo: 9 } } })
    render(<MemoryRouter initialEntries={['/demo/9']}><App /></MemoryRouter>)
    await user.click(await screen.findByText(/click anywhere to enter/i))
    await user.click(screen.getByRole('button', { name: /open the console/i }))
    expect(await screen.findByText(/Recorded demo 09/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /trace live/i })).toBeInTheDocument()
    // No case id, so nothing that reads or writes a case is offered.
    expect(screen.queryByText('Export')).not.toBeInTheDocument()
    expect(fetch.mock.calls.some(([url]) => /\/trace(\/jobs)?$/.test(String(url).split('?')[0]))).toBe(false)
  })

  it('asks for no name or password at either door, and says why', async () => {
    const user = userEvent.setup()
    for (const door of ['investigator', 'citizen']) {
      at(`/signin/${door}`)
      await user.click(await screen.findByText(/click anywhere to enter/i))
      expect(screen.getByText(/no accounts yet/i)).toBeInTheDocument()
      expect(screen.queryAllByRole('textbox')).toEqual([])
      expect(document.querySelector('input[type="password"]')).toBeNull()
      cleanup()
    }
  })

  it('says it is a demo on every page behind the door, and switches views', async () => {
    const user = userEvent.setup()
    sessionStorage.setItem('exchequer-demo-session', 'investigator')
    at('/')
    expect(await screen.findByRole('note', { name: 'Demo mode' })).toHaveTextContent(/no accounts yet · viewing as Investigator/)
    await user.click(screen.getByRole('button', { name: /switch to citizen view/i }))
    expect(await screen.findByText(/This page is still to be built/)).toBeInTheDocument()
    expect(screen.getByRole('note', { name: 'Demo mode' })).toHaveTextContent(/viewing as Citizen/)
  })

  it('forgets the view and the demo code on leaving', async () => {
    const user = userEvent.setup()
    sessionStorage.setItem('exchequer-demo-session', 'investigator')
    sessionStorage.setItem('exchequer-demo-code', 'river-otter-42')
    at('/')
    await user.click(await screen.findByRole('button', { name: 'Leave' }))
    expect(await screen.findByText(/click anywhere to enter/i)).toBeInTheDocument()
    expect(sessionStorage.getItem('exchequer-demo-session')).toBeNull()
    expect(sessionStorage.getItem('exchequer-demo-code')).toBeNull()
  })

  it('keeps a citizen out of the investigator console', async () => {
    sessionStorage.setItem('exchequer-demo-session', 'citizen')
    at('/')
    // The citizen page renders; the console's address field never does.
    expect(await screen.findByText(/This page is still to be built/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Reported wallet address')).not.toBeInTheDocument()
  })
})
