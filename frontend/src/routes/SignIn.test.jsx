import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../App'
import { DEMO_BUTTON } from '../../e2e/canary.lines.js'

// The investigator's door signs an officer in (backend/app/routes/accounts.py)
// and still lets anyone look around as a demo, as the judges do. The citizen's
// door is unchanged. jsdom has no WebGL, so the globe is a plain box.
vi.mock('../components/ExchangeGlobe', () => ({
  default: ({ onOpen, hint }) => <div data-testid="globe" onClick={onOpen}>{hint}</div>,
}))

const OFFICER = { id: 3, name: 'Asha Rao', email: 'asha@cell.in', role: 'officer', unit: { id: 1, name: 'Bengaluru CEN' }, active: true, must_change_password: false }
const health = { status: 'ok', default_chain: 'ethereum', chains: {} }

/** A fetch stub keyed by "METHOD /path"; anything else is a 404. */
function api(routes) {
  const fetch = vi.fn(async (url, init = {}) => {
    const key = `${init.method ?? 'GET'} ${String(url).replace(/^\/api/, '').split('?')[0]}`
    const hit = routes[key] ?? { status: 404, body: { detail: 'not stubbed' } }
    const { status = 200, body } = typeof hit === 'function' ? hit(init) : hit
    return new Response(JSON.stringify(body), { status })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}
const calls = (fetch, key) => fetch.mock.calls.filter(([url, init = {}]) => `${init.method ?? 'GET'} ${String(url).replace(/^\/api/, '').split('?')[0]}` === key)
const base = { 'GET /chains': { body: health }, 'GET /cases': { body: { count: 0, cases: [] } }, 'GET /access': { body: {} } }

async function door(path, routes) {
  const user = userEvent.setup()
  const fetch = api({ 'GET /auth/me': { body: { demo: true } }, ...base, ...routes })
  render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
  await user.click(await screen.findByText(/click anywhere to enter/i))
  return { user, fetch, card: within(screen.getByRole('dialog', { name: /enter as investigator/i })) }
}
const sidebar = async () => within(await screen.findByRole('complementary', { name: 'Sidebar' }))

describe('the investigator door', () => {
  it('asks an officer for an e-mail and password, and keeps the demo for everyone else', async () => {
    const { card } = await door('/signin/investigator')
    expect(card.getByLabelText('E-mail')).toHaveAttribute('autocomplete', 'username')
    expect(card.getByLabelText('Password')).toHaveAttribute('type', 'password')
    expect(card.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(card.getByRole('button', { name: 'Look around as a demo' })).toBeInTheDocument()
  })

  it('still offers the demo by the name the live-site canary clicks', async () => {
    const { card } = await door('/signin/investigator')
    expect(card.getByRole('button', { name: DEMO_BUTTON })).toBeInTheDocument()
  })

  it('signs an officer in and opens the console with their name and unit', async () => {
    const { user, fetch, card } = await door('/signin/investigator', { 'POST /auth/login': { body: OFFICER } })
    await user.type(card.getByLabelText('E-mail'), 'asha@cell.in')
    await user.type(card.getByLabelText('Password'), 'correct horse battery')
    await user.click(card.getByRole('button', { name: 'Sign in' }))
    const side = await sidebar()
    expect(side.getByText('Asha Rao')).toBeInTheDocument()
    expect(side.getByText('Bengaluru CEN')).toBeInTheDocument()
    expect(side.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
    expect(side.queryByText(/Demo mode/)).not.toBeInTheDocument()
    const [[, init]] = calls(fetch, 'POST /auth/login')
    expect(init.headers['X-Exchequer-Request']).toBe('1')
    expect(JSON.parse(init.body)).toEqual({ email: 'asha@cell.in', password: 'correct horse battery' })
    expect(sessionStorage.getItem('exchequer-demo-session')).toBeNull()
  })

  it("says why a sign-in failed in the backend's plain words, and stays at the door", async () => {
    const detail = 'That e-mail and password do not match an active account.'
    const { user, card } = await door('/signin/investigator', { 'POST /auth/login': { status: 401, body: { detail } } })
    await user.type(card.getByLabelText('E-mail'), 'asha@cell.in')
    await user.type(card.getByLabelText('Password'), 'wrong')
    await user.click(card.getByRole('button', { name: 'Sign in' }))
    expect(await card.findByRole('alert')).toHaveTextContent(detail)
    expect(card.getByLabelText('Password')).toHaveAttribute('aria-invalid', 'true')
    expect(card.getByLabelText('Password')).toHaveValue('')
    expect(card.getByLabelText('E-mail')).toHaveAccessibleDescription(detail)
    expect(card.getByLabelText('Password')).toHaveAccessibleDescription(detail)
  })

  it('asks for both fields before it asks the backend', async () => {
    const { user, fetch, card } = await door('/signin/investigator')
    await user.click(card.getByRole('button', { name: 'Sign in' }))
    expect(card.getByRole('alert')).toHaveTextContent('Enter your e-mail and password.')
    expect(calls(fetch, 'POST /auth/login')).toEqual([])
  })

  it('opens the demo with no account, as before', async () => {
    const { user, fetch, card } = await door('/signin/investigator')
    await user.click(card.getByRole('button', { name: 'Look around as a demo' }))
    expect((await sidebar()).getByText('Demo mode · Investigator')).toBeInTheDocument()
    expect(calls(fetch, 'POST /auth/login')).toEqual([])
  })

  it('has an officer with a temporary password choose their own before anything else', async () => {
    const fresh = { ...OFFICER, must_change_password: true }
    const { user, fetch, card } = await door('/signin/investigator', {
      'POST /auth/login': { body: fresh },
      'POST /auth/password': { body: OFFICER },
    })
    await user.type(card.getByLabelText('E-mail'), 'asha@cell.in')
    await user.type(card.getByLabelText('Password'), 'temp-pass-1234')
    await user.click(card.getByRole('button', { name: 'Sign in' }))
    expect(await card.findByRole('heading', { name: 'Choose your own password' })).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Sidebar' })).not.toBeInTheDocument()

    expect(card.getByLabelText('New password')).toHaveAccessibleDescription(/^At least 12 characters/)
    await user.type(card.getByLabelText('Temporary password'), 'temp-pass-1234')
    await user.type(card.getByLabelText('New password'), 'short')
    await user.type(card.getByLabelText('New password, again'), 'short')
    await user.click(card.getByRole('button', { name: 'Save and continue' }))
    expect(card.getByRole('alert')).toHaveTextContent('Use at least 12 characters.')
    expect(card.getByLabelText('New password')).toHaveAccessibleDescription(/^At least 12 characters.*Use at least 12 characters\.$/)

    await user.clear(card.getByLabelText('New password'))
    await user.type(card.getByLabelText('New password'), 'a long new passphrase')
    await user.click(card.getByRole('button', { name: 'Save and continue' }))
    expect(card.getByRole('alert')).toHaveTextContent('The two new passwords differ.')
    expect(calls(fetch, 'POST /auth/password')).toEqual([])

    await user.clear(card.getByLabelText('New password, again'))
    await user.type(card.getByLabelText('New password, again'), 'a long new passphrase')
    await user.click(card.getByRole('button', { name: 'Save and continue' }))
    expect((await sidebar()).getByText('Asha Rao')).toBeInTheDocument()
    const [[, init]] = calls(fetch, 'POST /auth/password')
    expect(init.headers['X-Exchequer-Request']).toBe('1')
    expect(JSON.parse(init.body)).toEqual({ current_password: 'temp-pass-1234', new_password: 'a long new passphrase' })
  })

  it('sends a tab whose session still has a temporary password to the change first', async () => {
    api({ 'GET /auth/me': { body: { ...OFFICER, must_change_password: true } }, ...base })
    render(<MemoryRouter initialEntries={['/cases']}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: 'Choose your own password' })).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Sidebar' })).not.toBeInTheDocument()
  })

  it('keeps the officer on the password change, and says so, when signing out there fails', async () => {
    const user = userEvent.setup()
    let refuse = true
    api({
      'GET /auth/me': { body: { ...OFFICER, must_change_password: true } }, ...base,
      'POST /auth/logout': () => (refuse ? { status: 503, body: { detail: 'Exchequer is busy.' } } : { body: { signed_out: true } }),
    })
    render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)
    await user.click(await screen.findByRole('button', { name: 'Sign out instead' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not sign out: Exchequer is busy.')
    expect(screen.getByRole('heading', { name: 'Choose your own password' })).toBeInTheDocument()
    refuse = false
    await user.click(screen.getByRole('button', { name: 'Sign out instead' }))
    expect(await screen.findByText(/click anywhere to enter/i)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Choose your own password' })).not.toBeInTheDocument()
  })

  it('lets a signed-in tab straight into the console, and signs it out', async () => {
    const user = userEvent.setup()
    const fetch = api({ 'GET /auth/me': { body: OFFICER }, 'POST /auth/logout': { body: { signed_out: true } }, ...base })
    render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)
    const side = await sidebar()
    await user.click(side.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByText(/click anywhere to enter/i)).toBeInTheDocument()
    const [[, init]] = calls(fetch, 'POST /auth/logout')
    expect(init.headers['X-Exchequer-Request']).toBe('1')
  })
})

describe('the citizen door', () => {
  it('asks for no name or password, and says why', async () => {
    const user = userEvent.setup()
    api({ 'GET /auth/me': { body: { demo: true } }, ...base })
    render(<MemoryRouter initialEntries={['/signin/citizen']}><App /></MemoryRouter>)
    await user.click(await screen.findByText(/click anywhere to enter/i))
    expect(screen.getByText(/no accounts yet/i)).toBeInTheDocument()
    expect(screen.queryAllByRole('textbox')).toEqual([])
    expect(document.querySelector('input[type="password"]')).toBeNull()
  })
})
