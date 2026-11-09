import { cleanup, render, screen, within } from '@testing-library/react'
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
    // The case's pill, and the shell's breadcrumb.
    expect(await screen.findAllByText(/Verified example 09/)).toHaveLength(2)
    // Inside the shell, which carries the one way home.
    expect(within(screen.getByRole('complementary', { name: 'Sidebar' })).getByRole('link', { name: 'Cases' })).toHaveAttribute('aria-current', 'true')
    expect(screen.getAllByRole('link', { name: 'Exchequer' })).toHaveLength(1)
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
    const side = within(await screen.findByRole('complementary', { name: 'Sidebar' }))
    expect(side.getByText('Demo mode · Investigator')).toBeInTheDocument()
    await user.click(side.getByRole('button', { name: /switch to citizen view/i }))
    expect(await screen.findByText(/This page is still to be built/)).toBeInTheDocument()
    expect(screen.getByRole('note', { name: 'Preview' })).toHaveTextContent(/no accounts yet · viewing as Citizen/)
  })

  it('forgets the view and the demo code on leaving', async () => {
    const user = userEvent.setup()
    sessionStorage.setItem('exchequer-demo-session', 'investigator')
    sessionStorage.setItem('exchequer-demo-code', 'river-otter-42')
    at('/')
    const side = within(await screen.findByRole('complementary', { name: 'Sidebar' }))
    await user.click(side.getByRole('button', { name: 'Leave' }))
    expect(await screen.findByText(/click anywhere to enter/i)).toBeInTheDocument()
    expect(sessionStorage.getItem('exchequer-demo-session')).toBeNull()
    expect(sessionStorage.getItem('exchequer-demo-code')).toBeNull()
  })

  it('gives each door a main landmark, so a screen reader can skip to it', async () => {
    for (const door of ['investigator', 'citizen']) {
      at(`/signin/${door}`)
      expect(await screen.findByRole('main')).toContainElement(screen.getByText(/click anywhere to enter/i))
      cleanup()
    }
  })

  it('keeps a citizen out of the investigator console', async () => {
    sessionStorage.setItem('exchequer-demo-session', 'citizen')
    at('/')
    // The citizen page renders; the console's address field never does.
    expect(await screen.findByText(/This page is still to be built/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Reported wallet address')).not.toBeInTheDocument()
  })
})

describe('the console shell', () => {
  const wallet = `0x${'ab'.repeat(20)}`
  const shellAt = (path, extra = {}) => {
    sessionStorage.setItem('exchequer-demo-session', 'investigator')
    stubFetch({ '/chains': { body: health }, '/cases': { body: { count: 0, cases: [] } }, '/access': { body: {} }, ...extra })
    return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
  }

  it('opens a searched wallet at its trace link and waits for a click', async () => {
    const user = userEvent.setup()
    shellAt('/')
    await user.type(await screen.findByRole('searchbox', { name: 'Wallet, transaction hash or case ID' }), `${wallet}{Enter}`)
    expect(await screen.findByRole('button', { name: 'Run this trace' })).toBeInTheDocument()
    expect(fetch.mock.calls.some(([url]) => /\/trace(\/jobs)?$/.test(String(url).split('?')[0]))).toBe(false)
  })

  it('puts a searched transaction hash into the new trace form', async () => {
    const user = userEvent.setup()
    const hash = `0x${'c'.repeat(64)}`
    shellAt('/cases', { '/trace/intake': { body: { payments: true } }, '/demos/recorded': { body: { demos: [] } } })
    await user.type(await screen.findByRole('searchbox', { name: 'Wallet, transaction hash or case ID' }), `${hash}{Enter}`)
    expect(await screen.findByRole('heading', { level: 1, name: 'New trace' })).toBeInTheDocument()
    expect(await screen.findByLabelText(/Victim's payment transaction hash/)).toHaveValue(hash)
  })

  it('opens each page of the sidebar inside the shell', async () => {
    const user = userEvent.setup()
    shellAt('/', { '/watches': { body: { watches: [] } }, '/alerts': { body: { alerts: [] } }, '/requests': { body: { requests: [] } } })
    const side = within(await screen.findByRole('complementary', { name: 'Sidebar' }))
    for (const [link, heading] of [['Cases', 'Cases'], ['Watchlist', 'Watchlist'], ['Requests', 'Requests']]) {
      await user.click(side.getByRole('link', { name: link }))
      expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument()
      expect(side.getByRole('link', { name: link })).toHaveAttribute('aria-current', 'page')
    }
  })

  it('keeps Verify a report public: in the shell for an officer, on its own for anyone else', async () => {
    stubFetch({ '/chains': { body: health }, '/signing-key': { status: 404, body: {} } })
    const { unmount } = render(<MemoryRouter initialEntries={['/verify']}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { level: 1, name: /issued by Exchequer/ })).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Sidebar' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('main')).toHaveLength(1)
    unmount()
    shellAt('/verify')
    expect(await screen.findByRole('heading', { level: 1, name: /issued by Exchequer/ })).toBeInTheDocument()
    expect(within(screen.getByRole('complementary', { name: 'Sidebar' })).getByRole('link', { name: 'Verify a report' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getAllByRole('main')).toHaveLength(1)
  })

  it('keeps the one shell when an officer opens Verify a report and comes back', async () => {
    const user = userEvent.setup()
    shellAt('/cases', { '/signing-key': { status: 404, body: {} } })
    const side = () => within(screen.getByRole('complementary', { name: 'Sidebar' }))
    await side().findByText(/chains? ready to trace/)
    const asked = () => fetch.mock.calls.filter(([url]) => String(url).split('?')[0].endsWith('/chains')).length
    const before = asked()
    await user.click(side().getByRole('link', { name: 'Verify a report' }))
    // Still the same sidebar: no second /chains, no "Connecting…" while it asks.
    expect(side().queryByText('Connecting…')).not.toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 1, name: /issued by Exchequer/ })).toBeInTheDocument()
    await user.click(side().getByRole('link', { name: 'Cases' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Cases' })).toBeInTheDocument()
    expect(side().queryByText('Connecting…')).not.toBeInTheDocument()
    expect(asked()).toBe(before)
  })
})
