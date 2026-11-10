import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import LettersTab from './LettersTab'

// The Letters tab: a switch over the letters the backend lists (in its
// order), the chosen draft on a paper sheet with its blanks marked, what was
// checked and what is left to fill, and PDF, Copy text and Mark as sent.
const B = '[____________________]'
const LETTER = (who) => [
  `From      : ${B} (name, rank, unit, official e-mail and phone)`,
  'Date      : 10 November 2026',
  `To        : ${who}`,
  '   about 635.000000 USDT of everything the reported address sent',
  '         received 635.000000 USDT in 2 transfer(s), 2024-12-19 14:36 IST (09:06 UTC)',
  '   This request is not about the wallet TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf itself.',
  `4. In exercise of the powers under ${B}`,
  '',
].join('\n')
const TETHER = `To        : Tether Operations Limited\nReference : ${B} (FIR / NCRP acknowledgement number)\n`
// The freeze-letter backend lists the urgent letters first; any to= it adds must work.
const LETTERS = [
  { to: 'exchange-freeze', title: 'Urgent freeze request to Bin​ance' },
  { to: 'exchange', title: 'Request to Binance' },
  { to: 'tether', title: 'Request to Tether' },
  { to: 'bank', title: 'Request to State Bank' },
]
const CASE = {
  case_id: 'c1', address: 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts', chain: 'tron', asset: 'USDT', direction: 'outgoing',
  exchange: 'Binance', exchange_address: 'TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf', exchange_label: 'Binance-Hot 7',
  estimates: { conservative: 635 }, intake: { mode: 'address', payments: [] },
}

function api(routes) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const [path, query = ''] = String(url).replace(/^\/api/, '').split('?')
    let body = init.body
    try { body = JSON.parse(body) } catch { /* none */ }
    calls.push({ method, path, query, body })
    const hit = routes[`${method} ${path}${query && routes[`${method} ${path}?${query}`] ? `?${query}` : ''}`]
    if (!hit) return new Response(JSON.stringify({ detail: 'not stubbed' }), { status: 404 })
    const { status = 200, body: out } = typeof hit === 'function' ? hit(body) : hit
    return new Response(typeof out === 'string' ? out : JSON.stringify(out), { status })
  }))
  return calls
}

const STORED = {
  'GET /trace/c1/letters': { body: { case_id: 'c1', letters: LETTERS } },
  'GET /trace/c1/letter?to=exchange-freeze': { body: LETTER('Binance — urgent') },
  'GET /trace/c1/letter?to=exchange': { body: LETTER('Binance') },
  'GET /trace/c1/letter?to=tether': { body: TETHER },
  'GET /trace/c1/letter?to=bank': { body: 'To        : State Bank\n' },
  'GET /trace/c1/requests': { body: { count: 0, requests: [] } },
  'GET /watches': { body: { count: 0, watches: [] } },
}

// An urgent letter's row in the freeze log as the backend shows it to this
// caller (freeze_requests.summary): whether they may sign it off, and if
// not, why. The officer states come from the server's session, not the page.
const ROW = { case_id: 'c1', recipient: 'Binance', kind: 'exchange-freeze', history: [], reference: '', notes: '', needs_signoff: true, signoff: null, mine: true }
const AWAITING = { ...ROW, request_id: 'r1', status: 'awaiting_signoff', can_sign_off: false, signoff_reason: 'You drafted this letter: a second officer of your unit must sign it off.' }
const SIGNED = { ...ROW, request_id: 'r1', status: 'ready', can_sign_off: false, signoff: { by: 'Bina Iyer', at: '2026-11-10T09:00:00+00:00' } }

const open = (result = CASE, recorded = null) => render(<MemoryRouter><LettersTab result={result} recorded={recorded} /></MemoryRouter>)
const sheet = () => screen.getByRole('article', { name: /^Draft: / })
// What a button says back sits beside the buttons, in the side column.
const side = () => screen.getByRole('complementary', { name: 'Letter checks' })

describe('the Letters tab, asked for one letter by a Flow card', () => {
  it('opens that letter on the sheet and puts the keyboard on its switch', async () => {
    api(STORED)
    render(<MemoryRouter><LettersTab result={CASE} recorded={null} pick="tether" /></MemoryRouter>)
    const tether = await screen.findByRole('button', { name: 'Request to Tether', pressed: true })
    await waitFor(() => expect(tether).toHaveFocus())
    expect(await screen.findByRole('article', { name: 'Draft: Request to Tether' })).toBeInTheDocument()
  })

  it('opens the information letter when the urgent freeze letter asked for is not listed', async () => {
    api({ ...STORED, 'GET /trace/c1/letters': { body: { case_id: 'c1', letters: LETTERS.slice(1) } } })
    render(<MemoryRouter><LettersTab result={CASE} recorded={null} pick="exchange-freeze" /></MemoryRouter>)
    const exchange = await screen.findByRole('button', { name: 'Request to Binance', pressed: true })
    await waitFor(() => expect(exchange).toHaveFocus())
  })

  it("opens the instant exchanger's information letter when its urgent one is not listed", async () => {
    const letters = [{ to: 'tether', title: 'Request to Tether' }, { to: 'instant', title: 'Request to ChangeNOW' }]
    api({ ...STORED, 'GET /trace/c1/letters': { body: { case_id: 'c1', letters } }, 'GET /trace/c1/letter?to=instant': { body: LETTER('ChangeNOW') } })
    render(<MemoryRouter><LettersTab result={CASE} recorded={null} pick="instant-freeze" /></MemoryRouter>)
    expect(await screen.findByRole('button', { name: 'Request to ChangeNOW', pressed: true })).toBeInTheDocument()
  })

  it('opens the first letter when the one asked for is not listed', async () => {
    api(STORED)
    render(<MemoryRouter><LettersTab result={CASE} recorded={null} pick="nobody" /></MemoryRouter>)
    expect(await screen.findByRole('button', { name: 'Urgent freeze request to Binance', pressed: true })).toBeInTheDocument()
  })
})

describe('the Letters tab of a stored case', () => {
  it('offers each letter the backend lists, in its order and named in plain text, and opens the first', async () => {
    api(STORED)
    open()
    const group = await screen.findByRole('group', { name: 'Letter to' })
    expect(within(group).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'Urgent freeze request to Binance', 'Request to Binance', 'Request to Tether', 'Request to State Bank',
    ])
    expect(within(group).getByRole('button', { name: 'Urgent freeze request to Binance' })).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByText(/Binance — urgent/)).toBeInTheDocument()
    expect(sheet()).toHaveAccessibleName('Draft: Urgent freeze request to Binance')
  })

  it('switches the sheet to the letter chosen, any to= included', async () => {
    const user = userEvent.setup()
    const calls = api(STORED)
    open()
    await screen.findByText(/Binance — urgent/)
    await user.click(screen.getByRole('button', { name: 'Request to Tether' }))
    expect(await screen.findByText(/Tether Operations Limited/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Request to Tether' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: 'Request to State Bank' }))
    expect(await screen.findByText('To: State Bank', { selector: '.ln' })).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/trace/c1/letter').map((c) => c.query)).toEqual(['to=exchange-freeze', 'to=tether', 'to=bank'])
  })

  it('marks each blank in red with a label saying what to fill, and counts them', async () => {
    api(STORED)
    open()
    await screen.findByText(/Binance — urgent/)
    const marks = sheet().querySelectorAll('mark.letter-blank')
    expect(marks).toHaveLength(2)
    expect(marks[0]).toHaveTextContent('Blank 1 of 2, for you to fill: From: name, rank, unit, official e-mail and phone')
    expect(marks[1]).toHaveTextContent('Blank 2 of 2, for you to fill: The legal provision')
    const fill = screen.getByRole('region', { name: 'For you to fill · 2' })
    expect(within(fill).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['From: name, rank, unit, official e-mail and phone', 'The legal provision'])
  })

  it('ticks only what the letter and case make true', async () => {
    const user = userEvent.setup()
    api(STORED)
    open()
    await screen.findByText(/Binance — urgent/)
    const checked = screen.getByRole('region', { name: 'Checked for you' })
    expect(within(checked).getAllByRole('listitem').map((li) => li.firstChild.textContent)).toEqual([
      "Asks about the deposits, not the wallet's owner", 'States 635 USDT', 'Dated in IST',
    ])
    await user.click(screen.getByRole('button', { name: 'Request to Tether' }))
    await screen.findByText(/Tether Operations Limited/)
    expect(screen.queryByRole('region', { name: 'Checked for you' })).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'For you to fill · 1' })).toBeInTheDocument()
  })

  it('copies the letter as the backend wrote it', async () => {
    const user = userEvent.setup()
    api(STORED)
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    open()
    await screen.findByText(/Binance — urgent/)
    // The status line is in the page before anything is said, so a screen
    // reader announces what it later says.
    expect(within(side()).getByRole('status')).toHaveTextContent('')
    await user.click(screen.getByRole('button', { name: 'Copy text' }))
    expect(writeText).toHaveBeenCalledWith(LETTER('Binance — urgent'))
    await waitFor(() => expect(within(side()).getByRole('status')).toHaveTextContent('Copied the letter.'))
  })

  it('when the browser will not copy, hands over the letter as written, selected in a box', async () => {
    const user = userEvent.setup()
    api(STORED)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(async () => { throw new Error('denied') }) }, configurable: true })
    open()
    await screen.findByText(/Binance — urgent/)
    await user.click(screen.getByRole('button', { name: 'Copy text' }))
    await waitFor(() => expect(within(side()).getByRole('alert')).toHaveTextContent(/would not copy/))
    const box = within(side()).getByRole('textbox', { name: /letter's text/ })
    // The server's own text: no hidden labels, indents kept.
    expect(box.value).toBe(LETTER('Binance — urgent'))
    expect(box).toHaveAttribute('readonly')
    expect(box).toHaveFocus()
    expect([box.selectionStart, box.selectionEnd]).toEqual([0, box.value.length])
  })

  it('keeps the screen-reader labels of the blanks out of a copy made by selecting the sheet', async () => {
    api(STORED)
    open()
    await screen.findByText(/Binance — urgent/)
    // Only the label carries the class that stops it being selected.
    for (const mark of sheet().querySelectorAll('mark.letter-blank')) {
      expect(mark.querySelector('.visually-hidden')).toHaveClass('no-copy')
    }
  })

  it('prints the sheet alone for a PDF', async () => {
    const user = userEvent.setup()
    api(STORED)
    const print = vi.spyOn(window, 'print').mockImplementation(() => {
      expect(document.documentElement).toHaveClass('print-letter')
    })
    open()
    await screen.findByText(/Binance — urgent/)
    await user.click(screen.getByRole('button', { name: /^PDF/ }))
    expect(print).toHaveBeenCalledTimes(1)
    window.dispatchEvent(new Event('afterprint'))
    expect(document.documentElement).not.toHaveClass('print-letter')
  })

  it('marks a letter as sent through the requests log, under its own kind, and the log shows it', async () => {
    const user = userEvent.setup()
    let items = []
    const calls = api({
      ...STORED,
      'GET /trace/c1/requests': () => ({ body: { count: items.length, requests: items } }),
      'POST /requests': (body) => {
        items = [{ request_id: 'r1', ...body, history: [], reference: '', notes: '' }]
        return { status: 201, body: items[0] }
      },
    })
    open()
    await screen.findByText(/Binance — urgent/)
    await user.click(screen.getByRole('button', { name: 'Request to Binance' }))
    await screen.findByText('To: Binance', { selector: '.ln' })
    await user.click(screen.getByRole('button', { name: 'Mark as sent' }))
    expect(calls.find((c) => c.method === 'POST').body).toEqual({
      case_id: 'c1', recipient: 'Binance', kind: 'exchange', address: CASE.exchange_address, asset: 'USDT', status: 'sent',
    })
    await waitFor(() => expect(within(side()).getByRole('status')).toHaveTextContent('Logged as sent to Binance.'))
    expect(await screen.findByText(/Freeze requests · 1/)).toBeInTheDocument()
    // The button says so and stays where the keyboard left it, doing nothing more.
    const done = screen.getByRole('button', { name: 'Marked as sent' })
    expect(done).toHaveAttribute('aria-disabled', 'true')
    expect(done).not.toBeDisabled()
    expect(done).toHaveFocus()
    await user.click(done)
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
    // A letter the log does not know is logged as "other", to the name in its title.
    await user.click(screen.getByRole('button', { name: 'Request to State Bank' }))
    await screen.findByText('To: State Bank', { selector: '.ln' })
    await user.click(screen.getByRole('button', { name: 'Mark as sent' }))
    expect(calls.filter((c) => c.method === 'POST')[1].body).toMatchObject({ recipient: 'State Bank', kind: 'other', address: '' })
  })

  it("logs an instant exchanger's letter with the wallet it is about", async () => {
    const user = userEvent.setup()
    const FF = 'TDoXUNZ6PajKuiUkcYg3EDSV9bnqGqsbcf'
    const letters = [{ to: 'instant-freeze', title: 'Urgent freeze request to FixedFloat', address: FF }]
    const calls = api({
      ...STORED,
      'GET /trace/c1/letters': { body: { case_id: 'c1', letters } },
      'GET /trace/c1/letter?to=instant-freeze': { body: LETTER('FixedFloat') },
      'POST /requests': (body) => ({ status: 201, body: { request_id: 'r1', ...body, history: [], reference: '', notes: '' } }),
    })
    render(<MemoryRouter><LettersTab result={CASE} recorded={null} /></MemoryRouter>)
    await screen.findByText('To: FixedFloat', { selector: '.ln' })
    // An urgent letter is logged when its drafter asks for the second officer's sign-off.
    await user.click(await within(await screen.findByRole('region', { name: 'Second officer' })).findByRole('button', { name: 'Ask for sign-off' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ recipient: 'FixedFloat', kind: 'instant-freeze', address: FF, status: 'awaiting_signoff' }))
  })

  it('reads a letter already logged as sent from the freeze log, and logs it no second time', async () => {
    const user = userEvent.setup()
    let items = [{ request_id: 'r1', case_id: 'c1', recipient: 'Binance', kind: 'exchange-freeze', status: 'sent', history: [], reference: '', notes: '' }]
    const calls = api({
      ...STORED,
      'GET /trace/c1/requests': () => ({ body: { count: items.length, requests: items } }),
      'DELETE /requests/r1': () => { items = []; return { body: { deleted: 'r1' } } },
    })
    open()
    await screen.findByText(/Binance — urgent/)
    const done = await screen.findByRole('button', { name: 'Marked as sent' })
    await user.click(done)
    expect(calls.some((c) => c.method === 'POST' || c.method === 'PATCH')).toBe(false)
    // The information letter to the same exchange is a different letter.
    await user.click(screen.getByRole('button', { name: 'Request to Binance' }))
    await screen.findByText('To: Binance', { selector: '.ln' })
    expect(screen.getByRole('button', { name: 'Mark as sent' })).not.toHaveAttribute('aria-disabled', 'true')
    // Removed from the log, it starts again: a second officer signs it off first.
    await user.click(screen.getByRole('button', { name: 'Urgent freeze request to Binance' }))
    await user.click(screen.getByRole('button', { name: 'Remove' }))
    expect(await screen.findByRole('button', { name: 'Ask for sign-off' })).toBeInTheDocument()
  })

  it('moves a signed-off request in the log on to sent, rather than logging a second one', async () => {
    const user = userEvent.setup()
    let items = [{ ...SIGNED, request_id: 'r1' }]
    const calls = api({
      ...STORED,
      'GET /trace/c1/requests': () => ({ body: { count: items.length, requests: items } }),
      'PATCH /requests/r1': (body) => { items = [{ ...items[0], ...body }]; return { body: items[0] } },
    })
    open()
    await screen.findByText(/Binance — urgent/)
    await screen.findByText(/Freeze requests · 1/)
    await user.click(screen.getByRole('button', { name: 'Mark as sent' }))
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([{ status: 'sent' }])
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    expect(await screen.findByRole('button', { name: 'Marked as sent' })).toHaveAttribute('aria-disabled', 'true')
  })

  it('says so when the case supports no letter, and keeps the freeze log and watches', async () => {
    api({ ...STORED, 'GET /trace/c1/letters': { body: { case_id: 'c1', letters: [] } } })
    open()
    expect(await screen.findByText(/supports no request letter/)).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Letter to' })).not.toBeInTheDocument()
    expect(screen.getByText(/Freeze requests · 0/)).toBeInTheDocument()
    expect(screen.getByText('Watch for movement')).toBeInTheDocument()
  })

  it('says why when a letter cannot be drafted', async () => {
    api({ ...STORED, 'GET /trace/c1/letter?to=exchange-freeze': { status: 400, body: { detail: 'This case reached no exchange.' } } })
    open()
    await waitFor(() => expect(within(sheet()).getByRole('alert')).toHaveTextContent('The letter could not be drafted: This case reached no exchange.'))
    expect(within(side()).getByRole('alert')).toBeEmptyDOMElement()
  })
})

describe('a second officer signs off an urgent freeze letter', () => {
  const card = () => screen.getByRole('region', { name: 'Second officer' })
  const log = (items, more = {}) => {
    const box = { items }
    const calls = api({ ...STORED, 'GET /trace/c1/requests': () => ({ body: { count: box.items.length, requests: box.items } }), ...more(box) })
    return calls
  }

  it('asks for a sign-off, and Mark as sent waits until there is one', async () => {
    const user = userEvent.setup()
    const calls = log([], (box) => ({
      'POST /requests': (body) => { box.items = [{ ...AWAITING, ...body }]; return { status: 201, body: box.items[0] } },
    }))
    open()
    await screen.findByText(/Binance — urgent/)
    expect(card()).toHaveTextContent('A second officer of your unit must approve this urgent letter before it is ready to send.')
    const sendButton = screen.getByRole('button', { name: 'Mark as sent' })
    expect(sendButton).toHaveAttribute('aria-disabled', 'true')
    await user.click(sendButton)
    expect(within(side()).getByRole('status')).toHaveTextContent('A second officer must sign this letter off before it can be marked as sent.')
    await user.click(within(card()).getByRole('button', { name: 'Ask for sign-off' }))
    expect(calls.find((c) => c.method === 'POST').body).toEqual({
      case_id: 'c1', recipient: 'Binance', kind: 'exchange-freeze', address: CASE.exchange_address, asset: 'USDT', status: 'awaiting_signoff',
    })
    await waitFor(() => expect(card()).toHaveTextContent("Awaiting a second officer's approval."))
    // The drafter is told why the button is not theirs, and gets none.
    expect(card()).toHaveTextContent('You drafted this letter: a second officer of your unit must sign it off.')
    expect(within(card()).queryByRole('button')).not.toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/trace/c1/letter' && c.query === 'to=exchange-freeze')).toHaveLength(2) // redrafted
  })

  it('moves a drafted request on to awaiting a sign-off', async () => {
    const user = userEvent.setup()
    const calls = log([{ ...ROW, request_id: 'r1', status: 'drafted', can_sign_off: false, signoff_reason: AWAITING.signoff_reason }], (box) => ({
      'PATCH /requests/r1': (body) => { box.items = [{ ...AWAITING, ...body }]; return { body: box.items[0] } },
    }))
    open()
    await user.click(await within(await screen.findByRole('region', { name: 'Second officer' })).findByRole('button', { name: 'Ask for sign-off' }))
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([{ status: 'awaiting_signoff' }])
  })

  it('lets an eligible officer sign it off, and then shows who did and when, in IST', async () => {
    const user = userEvent.setup()
    const calls = log([{ ...AWAITING, mine: false, can_sign_off: true, signoff_reason: null }], (box) => ({
      'POST /requests/r1/signoff': () => { box.items = [{ ...SIGNED, mine: false }]; return { body: box.items[0] } },
    }))
    open()
    const sign = await within(await screen.findByRole('region', { name: 'Second officer' })).findByRole('button', { name: 'Sign off' })
    await user.click(sign)
    const post = calls.find((c) => c.path === '/requests/r1/signoff')
    expect(post.method).toBe('POST')
    await waitFor(() => expect(card()).toHaveTextContent('Approved by Bina Iyer, 10 Nov 2026 14:30 IST.'))
    expect(within(side()).getByRole('status')).toHaveTextContent('Signed off. The letter is ready to send.')
    // Not this browser's request: its drafter logs it as sent.
    await user.click(screen.getByRole('button', { name: 'Mark as sent' }))
    expect(within(side()).getByRole('status')).toHaveTextContent('The officer who drafted this letter logs it as sent.')
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('sends the request header a sign-off needs', async () => {
    const user = userEvent.setup()
    const seen = []
    log([{ ...AWAITING, mine: false, can_sign_off: true, signoff_reason: null }], () => ({}))
    const stubbed = globalThis.fetch
    vi.stubGlobal('fetch', vi.fn((url, init = {}) => { seen.push(init.headers ?? {}); return stubbed(url, init) }))
    open()
    await user.click(await within(await screen.findByRole('region', { name: 'Second officer' })).findByRole('button', { name: 'Sign off' }))
    await waitFor(() => expect(seen.some((h) => h['X-Exchequer-Request'] === '1')).toBe(true))
  })

  it('tells anyone who may not sign it off why, with no button', async () => {
    const reason = 'A demo user cannot sign off a freeze letter: a second officer must sign in to their own account.'
    log([{ ...AWAITING, mine: false, signoff_reason: reason }], () => ({}))
    open()
    await waitFor(() => expect(card()).toHaveTextContent(reason))
    expect(within(card()).queryByRole('button')).not.toBeInTheDocument()
  })

  it('tells a caller who is not signed in, before any click, that no one could sign it off', async () => {
    const reason = 'An urgent freeze letter needs a signed-in drafter and a second officer of the same unit: sign in to ask for a sign-off.'
    api({ ...STORED, 'GET /trace/c1/requests': { body: { count: 0, requests: [], ask_reason: reason } } })
    open()
    await waitFor(() => expect(card()).toHaveTextContent(reason))
    expect(within(card()).queryByRole('button')).not.toBeInTheDocument()
  })

  it('says the same of a drafted row no unit could sign, with no Ask button', async () => {
    const reason = 'This letter was drafted without signing in, so no unit\'s officer can sign it off. Sign in and draft it again.'
    log([{ ...ROW, request_id: 'r1', status: 'drafted', can_sign_off: false, signoff_reason: reason, ask_reason: reason }], () => ({}))
    open()
    await waitFor(() => expect(card()).toHaveTextContent(reason))
    expect(within(card()).queryByRole('button')).not.toBeInTheDocument()
  })

  it('keeps the keyboard in the card after Ask for sign-off swaps its button for a note', async () => {
    const user = userEvent.setup()
    log([], (box) => ({
      'POST /requests': (body) => { box.items = [{ ...AWAITING, ...body }]; return { status: 201, body: box.items[0] } },
    }))
    open()
    await screen.findByText(/Binance — urgent/)
    within(card()).getByRole('button', { name: 'Ask for sign-off' }).focus()
    await user.keyboard('{Enter}')
    await waitFor(() => expect(card()).toHaveTextContent("Awaiting a second officer's approval."))
    await waitFor(() => expect(document.activeElement).toBe(card().querySelector('#lt-signoff-state')))
  })

  it('keeps the keyboard in the card after Sign off removes its button', async () => {
    const user = userEvent.setup()
    log([{ ...AWAITING, mine: false, can_sign_off: true, signoff_reason: null }], (box) => ({
      'POST /requests/r1/signoff': () => { box.items = [{ ...SIGNED, mine: false }]; return { body: box.items[0] } },
    }))
    open()
    ;(await within(await screen.findByRole('region', { name: 'Second officer' })).findByRole('button', { name: 'Sign off' })).focus()
    await user.keyboard('{Enter}')
    await waitFor(() => expect(card()).toHaveTextContent('Approved by Bina Iyer'))
    await waitFor(() => expect(document.activeElement).toBe(card().querySelector('#lt-signoff-state')))
  })

  it('marks nothing on an information letter', async () => {
    const user = userEvent.setup()
    log([], () => ({}))
    open()
    await screen.findByText(/Binance — urgent/)
    await user.click(screen.getByRole('button', { name: 'Request to Binance' }))
    await screen.findByText('To: Binance', { selector: '.ln' })
    expect(screen.queryByRole('region', { name: 'Second officer' })).not.toBeInTheDocument()
  })

  it('on a recorded example, says a recording cannot be signed off', async () => {
    api({
      'GET /demos/recorded/11/letters': { body: { case_id: null, recorded_demo: 11, letters: LETTERS.slice(0, 1) } },
      'GET /demos/recorded/11/letter?to=exchange-freeze': { body: LETTER('Binance — urgent') },
    })
    open({ ...CASE, case_id: null }, 11)
    await screen.findByText(/Binance — urgent/)
    expect(card()).toHaveTextContent('A recorded example cannot be signed off: Trace live stores it as a case.')
    expect(within(card()).queryByRole('button')).not.toBeInTheDocument()
  })
})

describe('the Letters tab of a recorded example', () => {
  const RECORDED = { ...CASE, case_id: null }

  it('shows the letter drafted from the recording, and asks for a stored case to mark it sent', async () => {
    const user = userEvent.setup()
    const calls = api({
      'GET /demos/recorded/11/letters': { body: { case_id: null, recorded_demo: 11, letters: LETTERS.slice(1, 3) } },
      'GET /demos/recorded/11/letter?to=exchange': { body: LETTER('Binance') },
    })
    open(RECORDED, 11)
    expect(await screen.findByText('To: Binance', { selector: '.ln' })).toBeInTheDocument()
    expect(screen.getByText(/need a stored case/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Mark as sent' }))
    // Beside the button pressed, not a letter's height below it.
    const prompt = within(side()).getByRole('status')
    await waitFor(() => expect(prompt).toHaveTextContent(/stored case/))
    expect(within(prompt).getByRole('link', { name: 'Open a stored case' })).toHaveAttribute('href', '/cases')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    expect(calls.some((c) => c.path.startsWith('/trace/'))).toBe(false)
  })
})

describe('the Letters tab of a case that reached its exchange through a swap', () => {
  it("logs the follow-on's exchange and address, not 'the exchange'", async () => {
    const user = userEvent.setup()
    const calls = api({ ...STORED, 'POST /requests': (body) => ({ status: 201, body: { request_id: 'r1', ...body, history: [] } }) })
    open({ ...CASE, asset: 'ETH', exchange: null, exchange_address: null, follow_ons: [{ asset: 'USDT', result: { exchange: 'Binance', exchange_address: '0xde9' } }] })
    await screen.findByText(/Binance — urgent/)
    // The urgent letter is logged when its drafter asks for the second officer's sign-off.
    await user.click(await within(await screen.findByRole('region', { name: 'Second officer' })).findByRole('button', { name: 'Ask for sign-off' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ recipient: 'Binance', address: '0xde9', asset: 'USDT' }))
  })
})

describe('the Letters tab of a trace that was not saved', () => {
  it('drafts nothing and says why', async () => {
    const calls = api({})
    open({ ...CASE, case_id: null })
    expect(screen.getByText(/This trace was not saved/)).toBeInTheDocument()
    await waitFor(() => expect(calls).toEqual([]))
    expect(screen.queryByRole('group', { name: 'Letter to' })).not.toBeInTheDocument()
  })
})

describe('a letter that fails to draft', () => {
  const once = (fails) => {
    let calls = 0
    return () => (++calls <= fails ? { status: 503, body: { detail: 'Service waking up' } } : { body: LETTER('Binance — urgent') })
  }

  it('says so on the sheet and drafts it again on Try again', async () => {
    const user = userEvent.setup()
    api({ ...STORED, 'GET /trace/c1/letter?to=exchange-freeze': once(1) })
    open()
    const failed = await within(await screen.findByRole('article', { name: /^Draft: Urgent freeze/ })).findByText(/The letter could not be drafted/)
    expect(failed).toHaveTextContent('Service waking up')
    expect(screen.queryByText('Drafting the letter…')).not.toBeInTheDocument()
    await user.click(within(sheet()).getByRole('button', { name: 'Try again' }))
    expect(await within(sheet()).findByText(/Binance — urgent/)).toBeInTheDocument()
    expect(within(side()).getByRole('button', { name: 'Copy text' })).toBeEnabled()
    expect(sheet()).toHaveFocus()
  })

  it('drafts it again when its own letter button is pressed', async () => {
    const user = userEvent.setup()
    api({ ...STORED, 'GET /trace/c1/letter?to=exchange-freeze': once(1) })
    open()
    await within(await screen.findByRole('article', { name: /^Draft: Urgent freeze/ })).findByText(/The letter could not be drafted/)
    await user.click(screen.getByRole('button', { name: /Urgent freeze request/, pressed: true }))
    expect(await within(sheet()).findByText(/Binance — urgent/)).toBeInTheDocument()
  })
})
