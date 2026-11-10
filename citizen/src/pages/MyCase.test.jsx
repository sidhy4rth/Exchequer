import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App.jsx'
import { OFFLINE, fakeServer } from '../test/server.js'

const HASH = 'fde547813899a616a09c79842f0a413ac561505e0baa6db6b11f910a34a02e8e'
const WALLET = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
const WRONG = 'That NCRP number and tracking code do not match. Check both and try again.'
const OUT = [401, { error: 'Please sign in again.' }]

// What GET /api/my-case answers (citizen/api/_lib/complaint.py view), plus
// officer-only fields a faulty server might add: none of them may show.
const CASE = {
  reference: 'EXQ-7KQ2M9PD', sent_at: '2026-11-08T06:30:00+00:00',
  status: { key: 'with_cell', text: 'With a cyber cell' },
  sent: { name: 'Asha Rao', mobile: '', started: '2026-10-02', app: 'GoldWin Trade', link: '', contacts: '',
    upi: 'goldwin@upi', story: 'A mentor on Telegram showed me profits.' },
  payments: [{ hash: HASH, amount: '2500', token: 'USDT', network: 'Tron (TRC20)', paidAt: '2026-10-05T14:30',
    wallet: WALLET }],
  messages: [
    { from: 'Cyber cell', body: 'We have your complaint and are reading it.', at: '2026-11-09T05:00:00+00:00' },
    { from: 'You', body: 'Thank you. I have more chats.', at: '2026-11-09T06:15:00+00:00' },
  ],
  wallet_match: 'complaint,case', exchange: 'Binance', labels: ['Hot wallet 7'], flags: ['watchlist'],
  other_complaints: 3, hit_rate: 0.42, letters: ['freeze letter'],
}

const at = () => render(<MemoryRouter initialEntries={['/my-case']}><App /></MemoryRouter>)
const signInForm = () => screen.findByRole('form', { name: 'Sign in' })

async function signIn(user, ncrp = '31234567890123', code = 'ABCD-EFGH-JKMN') {
  await signInForm()
  await user.type(screen.getByLabelText('NCRP acknowledgement number'), ncrp)
  await user.type(screen.getByLabelText('Tracking code'), code)
  await user.click(screen.getByRole('button', { name: 'Open my complaint' }))
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('sign in (C6)', () => {
  it('asks for the NCRP number and the tracking code, and sends no SMS or e-mail', async () => {
    fakeServer({ 'GET /api/my-case': OUT })
    at()
    await signInForm()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Follow your complaint')
    expect(screen.getByLabelText('NCRP acknowledgement number')).toHaveAttribute('autocomplete', 'off')
    expect(screen.getByLabelText('Tracking code')).toHaveAccessibleDescription(/shown once when you sent your complaint/)
    const main = screen.getByRole('main')
    expect(main).toHaveTextContent(/Never share this code with anyone who calls you, even someone who says they are police\./)
    expect(main).toHaveTextContent(/cannot show it again or send it to you/)
    expect(main).not.toHaveTextContent(/code sent to your mobile|we send a code|SMS code|e-mail you/i)
    // A first visit is not an error.
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('link', { name: /complaint pack/i })).toHaveAttribute('href', '/report/pack')
  })

  it('checks both answers on the device first', async () => {
    const server = fakeServer({ 'GET /api/my-case': OUT })
    const user = userEvent.setup()
    at()
    await signInForm()
    await user.click(screen.getByRole('button', { name: 'Open my complaint' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Give the NCRP acknowledgement number')
    expect(screen.getByLabelText('NCRP acknowledgement number')).toHaveFocus()
    await user.type(screen.getByLabelText('NCRP acknowledgement number'), '3123 4567 8901')
    await user.click(screen.getByRole('button', { name: 'Open my complaint' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Give the tracking code')
    expect(screen.getByLabelText('Tracking code')).toHaveFocus()
    expect(server.calls.filter((c) => c.path === '/api/session')).toHaveLength(0)
  })

  it('says plainly when the number and code do not match', async () => {
    fakeServer({ 'GET /api/my-case': OUT, 'POST /api/session': [401, { error: WRONG }] })
    const user = userEvent.setup()
    at()
    await signIn(user)
    expect(await screen.findByRole('alert')).toHaveTextContent(WRONG)
    expect(screen.getByLabelText('NCRP acknowledgement number')).toHaveValue('31234567890123')
    expect(screen.getByLabelText('Tracking code')).toHaveValue('')
  })

  it('says how long to wait after too many wrong tries', async () => {
    fakeServer({ 'GET /api/my-case': OUT, 'POST /api/session': [429,
      { error: 'Too many wrong tries. Please wait a little and try again.' }, { 'Retry-After': '240' }] })
    const user = userEvent.setup()
    at()
    await signIn(user)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Too many wrong tries. Please wait a little and try again.')
    expect(alert).toHaveTextContent('You can try again in about 4 minutes.')
  })

  it('says when the site cannot be reached', async () => {
    fakeServer({ 'GET /api/my-case': OUT, 'POST /api/session': OFFLINE })
    const user = userEvent.setup()
    at()
    await signIn(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not reach the site.')
  })

  it('opens the complaint once the code is right', async () => {
    let signedIn = false
    const server = fakeServer({
      'GET /api/my-case': () => (signedIn ? [200, CASE] : OUT),
      'POST /api/session': () => { signedIn = true; return [200, { signed_in: true }] },
    })
    const user = userEvent.setup()
    at()
    await signIn(user, ' 3123-4567-8901-23 ', 'abcd efgh jkmn')
    // The form and its button are gone: focus moves to the complaint's heading.
    expect(await screen.findByRole('heading', { level: 1, name: 'My complaint' })).toHaveFocus()
    expect(server.calls.find((c) => c.path === '/api/session').body)
      .toEqual({ ncrp: '3123-4567-8901-23', code: 'abcd efgh jkmn' })
  })
})

describe('my case (C7)', () => {
  it('leaves focus where the page put it when it opens signed in', async () => {
    fakeServer({ 'GET /api/my-case': [200, CASE] })
    at()
    const head = await screen.findByRole('heading', { level: 1, name: 'My complaint' })
    expect(head).not.toHaveFocus()
  })

  it('shows the four steps, with the current one marked', async () => {
    fakeServer({ 'GET /api/my-case': [200, CASE] })
    at()
    const steps = within(await screen.findByRole('list', { name: 'Where your complaint is' })).getAllByRole('listitem')
    expect(steps.map((li) => li.querySelector('.step-title').textContent))
      .toEqual(['Received', 'With a cyber cell', 'Under investigation', 'Closed'])
    expect(steps[0]).toHaveTextContent(/Done.*your complaint and 1 payment/)
    expect(steps[1]).toHaveAttribute('aria-current', 'step')
    expect(steps[1]).toHaveTextContent(/Now/)
    expect(steps[2]).toHaveTextContent(/Not yet/)
    expect(screen.getByText('EXQ-7KQ2M9PD')).toBeInTheDocument()
  })

  it('marks every step done once the complaint is closed', async () => {
    fakeServer({ 'GET /api/my-case': [200, { ...CASE, status: { key: 'closed', text: 'Closed' }, payments: [] }] })
    at()
    const steps = within(await screen.findByRole('list', { name: 'Where your complaint is' })).getAllByRole('listitem')
    expect(steps[3]).toHaveAttribute('aria-current', 'step')
    expect(steps[0]).toHaveTextContent(/your complaint$/)
    expect(steps.filter((li) => li.classList.contains('done'))).toHaveLength(4)
  })

  it('shows the messages, what the citizen gave, and the recovery-scam warning, and nothing for officers', async () => {
    fakeServer({ 'GET /api/my-case': [200, CASE] })
    at()
    const thread = within(await screen.findByRole('list', { name: 'Messages' })).getAllByRole('listitem')
    expect(thread[0]).toHaveTextContent(/Cyber cell.*9 Nov 2026, 10:30 am IST.*We have your complaint/)
    expect(thread[1]).toHaveTextContent(/You.*Thank you\. I have more chats\./)
    const gave = within(screen.getByRole('region', { name: 'What you gave us' }))
    expect(gave.getByText('2,500 USDT')).toBeInTheDocument()
    expect(gave.getByText(HASH)).toBeInTheDocument()
    expect(gave.getByText(WALLET)).toBeInTheDocument()
    expect(gave.getByText('GoldWin Trade')).toBeInTheDocument()
    expect(gave.getByText(/Screenshots.*kept on your device/i)).toBeInTheDocument()
    const main = screen.getByRole('main')
    expect(main).toHaveTextContent(
      'Updates come only here. Anyone who calls offering to get your money back for a fee is a scammer.')
    expect(main.textContent).not.toMatch(/Binance|Hot wallet|watchlist|freeze letter|0\.42|other complaints/i)
    expect(screen.getByText('Police never charge a fee to recover money.')).toBeVisible()
    expect(screen.getByText('We never ask for your seed phrase or private key.')).toBeVisible()
  })

  it('says when no message has come yet', async () => {
    fakeServer({ 'GET /api/my-case': [200, { ...CASE, messages: [] }] })
    at()
    expect(await screen.findByText(/No messages yet/)).toBeInTheDocument()
  })

  it('sends a reply and shows it in the thread', async () => {
    let messages = CASE.messages
    const server = fakeServer({
      'GET /api/my-case': () => [200, { ...CASE, messages }],
      'POST /api/messages': (req) => {
        messages = [...messages, { from: 'You', body: req.body.body, at: '2026-11-10T04:00:00+00:00' }]
        return [201, { sent: true }]
      },
    })
    const user = userEvent.setup()
    at()
    const box = await screen.findByLabelText('Write to the cyber cell')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Write a message first.')
    expect(server.calls.filter((c) => c.path === '/api/messages')).toHaveLength(0)
    await user.type(box, 'The app has gone offline.')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    const thread = screen.getByRole('list', { name: 'Messages' })
    expect(await within(thread).findByText('The app has gone offline.')).toBeInTheDocument()
    expect(box).toHaveValue('')
    expect(server.calls.find((c) => c.path === '/api/messages').body).toEqual({ body: 'The app has gone offline.' })
  })

  it('keeps the reply when it cannot be sent, and says why', async () => {
    fakeServer({ 'GET /api/my-case': [200, CASE],
      'POST /api/messages': [429, { error: 'Too many tries for now. Please try again later.' }, { 'Retry-After': '30' }] })
    const user = userEvent.setup()
    at()
    await user.type(await screen.findByLabelText('Write to the cyber cell'), 'Hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Too many tries for now.*in about a minute/)
    expect(screen.getByLabelText('Write to the cyber cell')).toHaveValue('Hello')
  })

  it('goes back to sign in when the session has run out', async () => {
    fakeServer({ 'GET /api/my-case': [200, CASE], 'POST /api/messages': OUT })
    const user = userEvent.setup()
    at()
    await user.type(await screen.findByLabelText('Write to the cyber cell'), 'Hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await signInForm()
    expect(screen.getByRole('alert')).toHaveTextContent('Please sign in again.')
    expect(screen.getByRole('heading', { level: 1, name: 'Follow your complaint' })).toHaveFocus()
  })

  it('signs out', async () => {
    let signedIn = true
    const server = fakeServer({
      'GET /api/my-case': () => (signedIn ? [200, CASE] : OUT),
      'POST /api/logout': () => { signedIn = false; return [200, { signed_in: false }] },
    })
    const user = userEvent.setup()
    at()
    await user.click(await screen.findByRole('button', { name: 'Sign out' }))
    await signInForm()
    expect(screen.getByRole('heading', { level: 1, name: 'Follow your complaint' })).toHaveFocus()
    expect(screen.getByRole('status')).toHaveTextContent('You are signed out.')
    expect(server.calls.some((c) => c.path === '/api/logout' && c.method === 'POST')).toBe(true)
    expect(screen.queryByText('EXQ-7KQ2M9PD')).toBeNull()
  })

  it('offers to try again when the complaint cannot be loaded', async () => {
    let up = false
    fakeServer({ 'GET /api/my-case': () => (up ? [200, CASE]
      : [503, { error: 'This site cannot take requests right now. Please try again later.' }]) })
    const user = userEvent.setup()
    at()
    expect(await screen.findByRole('alert')).toHaveTextContent('This site cannot take requests right now.')
    up = true
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'My complaint' })).toBeInTheDocument()
  })

  it('passes the axe structural rules signed out with an error, and signed in', async () => {
    fakeServer({ 'GET /api/my-case': OUT, 'POST /api/session': [401, { error: WRONG }] })
    const user = userEvent.setup()
    const { container, unmount } = at()
    await signIn(user)
    await screen.findByRole('alert')
    const rules = { rules: { 'color-contrast': { enabled: false } } }
    const out = await axe.run(container, rules)
    expect(out.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`)).toEqual([])
    unmount()
    fakeServer({ 'GET /api/my-case': [200, CASE] })
    const second = at()
    await screen.findByRole('list', { name: 'Messages' })
    const inside = await axe.run(second.container, rules)
    expect(inside.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`)).toEqual([])
  })
})
