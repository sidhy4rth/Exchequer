import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App.jsx'
import { OFFLINE, fakeServer } from '../test/server.js'

const HASH = 'fde547813899a616a09c79842f0a413ac561505e0baa6db6b11f910a34a02e8e'
const WALLET = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
const KEY = 'exchequer-citizen-pack'

const at = () => render(<MemoryRouter initialEntries={['/report/pack']}><App /></MemoryRouter>)
const paper = () => screen.getByRole('region', { name: 'Complaint pack' })
const payment = (n) => within(screen.getByRole('group', { name: `Payment ${n}` }))
const save = (user) => user.click(screen.getByRole('button', { name: /Save as PDF/ }))
const addPayment = (user) => user.click(screen.getByRole('button', { name: 'Add another payment' }))
const shots = () => screen.getByLabelText('Add screenshots of the chats and the app')

async function fill(user, label, text, scope = screen) {
  const box = scope.getByLabelText(label)
  await user.clear(box)
  await user.click(box)
  await user.paste(text)
}

let print
beforeEach(() => {
  sessionStorage.clear()
  print = vi.spyOn(window, 'print').mockImplementation(() => {})
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('complaint pack', () => {
  it('is step 3 of 3, with step 1 a link back and step 2 reached from it', () => {
    at()
    const steps = within(screen.getByRole('list', { name: 'Report steps' })).getAllByRole('listitem')
    expect(steps[2]).toHaveAttribute('aria-current', 'step')
    expect(within(steps[0]).getByRole('link', { name: /Find your payment/ })).toHaveAttribute('href', '/report')
    expect(steps[1]).toHaveTextContent('Confirm it')
    expect(steps[1]).not.toHaveTextContent(/coming later/)
  })

  it('asks for what the portal and a cyber cell need, name and mobile optional', () => {
    at()
    for (const label of ['Your name (optional)', 'Your mobile number (optional)', 'When it started',
      'App or website name', 'Link to the app or website', 'Phone numbers and chat usernames they used',
      'UPI IDs or bank accounts you paid', 'What happened, in your words']) {
      expect(screen.getByLabelText(label)).toBeInTheDocument()
    }
    for (const label of ['Transaction hash', 'Amount', 'Token', 'Network', 'Date and time', 'Wallet you paid']) {
      expect(payment(1).getByLabelText(label)).toBeInTheDocument()
    }
    expect(shots()).toHaveAttribute('type', 'file')
  })

  it('checks the mobile, hash, amount and wallet before saving, and points to the first problem', async () => {
    const user = userEvent.setup()
    at()
    const mobile = screen.getByLabelText('Your mobile number (optional)')
    await fill(user, 'Your mobile number (optional)', '98765')
    await fill(user, 'Transaction hash', WALLET, payment(1))
    await fill(user, 'Amount', 'ten thousand', payment(1))
    await fill(user, 'Wallet you paid', HASH, payment(1))
    await save(user)
    expect(print).not.toHaveBeenCalled()
    expect(mobile).toHaveFocus()
    expect(mobile).toHaveAttribute('aria-invalid', 'true')
    expect(mobile).toHaveAccessibleDescription(/10-digit mobile number/)
    // The hash check is C3's: a wallet address is not a payment.
    expect(payment(1).getByLabelText('Transaction hash')).toHaveAccessibleDescription(/wallet address, not a payment/)
    expect(payment(1).getByLabelText('Amount')).toHaveAccessibleDescription(/as a number/)
    expect(payment(1).getByLabelText('Wallet you paid')).toHaveAccessibleDescription(/transaction hash, not a wallet/)
    expect(screen.getByRole('status')).toHaveTextContent('Check the 4 answers marked in red first.')

    await fill(user, 'Transaction hash', `0x${HASH.slice(4)}`, payment(1))
    expect(payment(1).getByLabelText('Transaction hash')).toHaveAccessibleDescription(/60 characters.*64/)

    // Fixed, it saves, with the hash taken out of the link pasted around it.
    await fill(user, 'Your mobile number (optional)', '+91 98765 43210')
    await fill(user, 'Transaction hash', `https://tronscan.org/#/transaction/${HASH}`, payment(1))
    await fill(user, 'Amount', '9,890.50', payment(1))
    await fill(user, 'Wallet you paid', WALLET, payment(1))
    expect(mobile).not.toHaveAttribute('aria-invalid')
    await save(user)
    expect(print).toHaveBeenCalledTimes(1)
    expect(within(paper()).getByText(HASH).tagName).toBe('DD')
  })

  it('takes any wallet on another network, and an empty pack, since anything can be left empty', async () => {
    const user = userEvent.setup()
    at()
    await save(user)
    expect(print).toHaveBeenCalledTimes(1)
    await fill(user, 'Wallet you paid', 'bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh', payment(1))
    await save(user)
    expect(payment(1).getByLabelText('Wallet you paid')).toHaveAttribute('aria-invalid', 'true')
    await user.selectOptions(payment(1).getByLabelText('Network'), 'Another network')
    await save(user)
    expect(print).toHaveBeenCalledTimes(2)
  })

  it('takes any hash and wallet on another network, but still catches a wallet in the hash', async () => {
    const user = userEvent.setup()
    at()
    const solana = '5VERv8NMvzbJMEkV8xnrLkEaWRtSz9CosKDYjCJjBRnbJLgp8uirBgmQpjKhoR4tjF3ZpRzrFmBV6UjKdiSZkQUW'
    const ton = `0:${'a'.repeat(63)}b`
    await fill(user, 'Transaction hash', solana, payment(1))
    await fill(user, 'Wallet you paid', ton, payment(1))
    await save(user)
    expect(print).not.toHaveBeenCalled()
    expect(payment(1).getByLabelText('Transaction hash')).toHaveAccessibleDescription(/choose "Another network"/)
    await user.selectOptions(payment(1).getByLabelText('Network'), 'Another network')
    await save(user)
    expect(print).toHaveBeenCalledTimes(1)
    expect(within(paper()).getByText(solana).tagName).toBe('DD')
    expect(within(paper()).getByText(ton).tagName).toBe('DD')
    await fill(user, 'Transaction hash', WALLET, payment(1))
    await save(user)
    expect(print).toHaveBeenCalledTimes(1)
    expect(payment(1).getByLabelText('Transaction hash')).toHaveAccessibleDescription(/wallet address, not a payment/)
  })

  it('takes more than one payment, and removes one', async () => {
    const user = userEvent.setup()
    at()
    expect(screen.queryByRole('button', { name: /Remove payment/ })).toBeNull()
    await fill(user, 'Amount', '100', payment(1))
    await addPayment(user)
    expect(payment(2).getByLabelText('Transaction hash')).toHaveFocus()
    await fill(user, 'Amount', '200', payment(2))
    await user.click(payment(1).getByRole('button', { name: 'Remove payment 1' }))
    expect(screen.queryByRole('group', { name: 'Payment 2' })).toBeNull()
    expect(payment(1).getByLabelText('Amount')).toHaveValue('200')
    expect(screen.getByRole('button', { name: 'Add another payment' })).toHaveFocus()
  })

  it('lays every answer out on the printed pack, headed as the citizen\'s own, and sends nothing', async () => {
    const network = vi.fn()
    vi.stubGlobal('fetch', network)
    vi.stubGlobal('XMLHttpRequest', network)
    const user = userEvent.setup()
    at()
    await fill(user, 'Your name (optional)', 'Asha Rao')
    await fill(user, 'Your mobile number (optional)', '9876543210')
    fireEvent.change(screen.getByLabelText('When it started'), { target: { value: '2026-10-02' } })
    await fill(user, 'App or website name', 'GoldWin Trade')
    await fill(user, 'Link to the app or website', 'goldwin-trade.example')
    await fill(user, 'Phone numbers and chat usernames they used', '+91 90000 11111\n@goldwin_mentor')
    await fill(user, 'UPI IDs or bank accounts you paid', 'goldwin@upi')
    await fill(user, 'What happened, in your words', 'A mentor on Telegram showed me profits.')
    await fill(user, 'Transaction hash', HASH, payment(1))
    await fill(user, 'Amount', '9,890', payment(1))
    await fill(user, 'Token', 'USDT', payment(1))
    await user.selectOptions(payment(1).getByLabelText('Network'), 'Tron (TRC20)')
    fireEvent.change(payment(1).getByLabelText('Date and time'), { target: { value: '2026-10-05T14:30' } })
    await fill(user, 'Wallet you paid', WALLET, payment(1))
    await addPayment(user)
    await fill(user, 'Amount', '0.5', payment(2))
    await fill(user, 'Token', 'ETH', payment(2))
    await addPayment(user)
    await user.upload(shots(), [new File(['a'], 'chat-1.png', { type: 'image/png' }),
      new File(['b'], 'app.jpg', { type: 'image/jpeg' })])
    await save(user)

    expect(print).toHaveBeenCalledTimes(1)
    expect(paper()).toHaveTextContent(/Prepared by the complainant.*This is not an official document/)
    for (const text of ['Asha Rao', '9876543210', '2026-10-02', 'GoldWin Trade', 'goldwin-trade.example',
      '+91 90000 11111', '@goldwin_mentor', 'goldwin@upi', 'A mentor on Telegram showed me profits.', HASH,
      '9,890 USDT', 'Tron (TRC20)', '2026-10-05 14:30', WALLET, '0.5 ETH', 'chat-1.png', 'app.jpg']) {
      expect(paper()).toHaveTextContent(text)
    }
    // The empty third payment is left off.
    const pack = within(paper())
    expect(pack.getByRole('heading', { name: 'Payment 2' })).toBeInTheDocument()
    expect(pack.queryByRole('heading', { name: 'Payment 3' })).toBeNull()
    expect(network).not.toHaveBeenCalled()
  })

  it('lists the screenshots by name only, never reading them', async () => {
    const read = vi.fn()
    vi.stubGlobal('FileReader', read)
    const files = ['chat-1.png', 'app.jpg'].map((name) => {
      const file = new File(['private'], name, { type: 'image/png' })
      for (const method of ['text', 'arrayBuffer', 'slice', 'stream', 'bytes']) file[method] = read
      return file
    })
    const user = userEvent.setup()
    at()
    expect(screen.getByRole('main')).toHaveTextContent(/files stay on your device/)
    await user.upload(shots(), files)
    await user.upload(shots(), files.slice(0, 1))
    const list = within(screen.getByRole('list', { name: 'Your screenshots' }))
    expect(list.getAllByRole('listitem')).toHaveLength(2)
    await user.click(list.getByRole('button', { name: 'Remove chat-1.png' }))
    expect(list.getAllByRole('listitem')).toHaveLength(1)
    expect(shots()).toHaveFocus()
    expect(read).not.toHaveBeenCalled()
  })

  it('keeps the draft in this tab only, and clears it', async () => {
    const user = userEvent.setup()
    const { unmount } = at()
    await fill(user, 'Your name (optional)', 'Asha Rao')
    await fill(user, 'Amount', '100', payment(1))
    await user.upload(shots(), new File(['a'], 'chat-1.png', { type: 'image/png' }))
    expect(JSON.parse(sessionStorage.getItem(KEY))).toMatchObject({ name: 'Asha Rao', files: ['chat-1.png'] })
    expect(localStorage.length).toBe(0)
    unmount()
    at()
    expect(screen.getByLabelText('Your name (optional)')).toHaveValue('Asha Rao')
    expect(payment(1).getByLabelText('Amount')).toHaveValue('100')

    const ask = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await user.click(screen.getByRole('button', { name: 'Clear this form' }))
    expect(screen.getByLabelText('Your name (optional)')).toHaveValue('Asha Rao')
    ask.mockReturnValue(true)
    await user.click(screen.getByRole('button', { name: 'Clear this form' }))
    expect(screen.getByLabelText('Your name (optional)')).toHaveValue('')
    expect(payment(1).getByLabelText('Amount')).toHaveValue('')
    expect(screen.queryByRole('list', { name: 'Your screenshots' })).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('The form is cleared.')
    expect(sessionStorage.getItem(KEY)).toBeNull()
  })

  it('still works when the browser blocks storage', async () => {
    const blocked = () => { throw new Error('blocked') }
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(blocked)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(blocked)
    const user = userEvent.setup()
    at()
    await fill(user, 'Your name (optional)', 'Asha Rao')
    await save(user)
    expect(print).toHaveBeenCalledTimes(1)
    expect(paper()).toHaveTextContent('Asha Rao')
  })

  it('says what to do with the pack next, and that nothing is sent', () => {
    at()
    const next = screen.getByRole('region', { name: 'Then report it' })
    expect(next).toHaveTextContent(/Upload it with your screenshots at cybercrime\.gov\.in.*nearest cyber cell/)
    expect(next).toHaveTextContent(/Call 1930/)
    expect(within(next).getByRole('link', { name: /Call 1930/ })).toHaveAttribute('href', 'tel:1930')
    expect(within(next).getByRole('link', { name: /cybercrime\.gov\.in/ }))
      .toHaveAttribute('href', 'https://cybercrime.gov.in')
    expect(screen.getByRole('main')).toHaveTextContent(
      /Nothing you type here is sent unless you choose Send to the cyber cell queue/)
  })

  it('says how to save on a phone, and promises no more than the page does', () => {
    at()
    const main = screen.getByRole('main')
    // An iPhone saves the PDF through Share; in-app browsers may not print at all.
    expect(main).toHaveTextContent(/on an iPhone, tap Share, then Save to Files/)
    expect(main).toHaveTextContent(/If nothing opens, open this page in Chrome or Safari/)
    // A reopened tab can bring the draft back, so a shared device needs clearing.
    expect(main).not.toHaveTextContent(/until you close it/)
    expect(main).toHaveTextContent(/On a shared device, press Clear this form when you are done/)
    // Only name and mobile are marked optional, so the lede says so for the rest.
    expect(main).not.toHaveTextContent(/Every answer is optional/)
    expect(main).toHaveTextContent(/You can leave anything empty/)
  })

  it('passes the axe structural rules with problems shown, two payments and a screenshot', async () => {
    const user = userEvent.setup()
    const { container } = at()
    await fill(user, 'Your mobile number (optional)', '1')
    await addPayment(user)
    await user.upload(shots(), new File(['a'], 'chat-1.png', { type: 'image/png' }))
    await save(user)
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`)).toEqual([])
  })
})

describe('sending the pack to the cyber cell queue', () => {
  const CODE = 'ABCD-EFGH-JKMN'
  const SENT = [201, { reference: 'EXQ-7KQ2M9PD', tracking_code: CODE }]
  const card = () => within(screen.getByRole('region', { name: 'Send to the cyber cell queue' }))
  const send = (user) => user.click(card().getByRole('button', { name: 'Send to the cyber cell queue' }))
  const agree = (user) => user.click(card().getByRole('checkbox'))

  it('says exactly what is sent, and that screenshots stay on the device', () => {
    at()
    const consent = card().getByRole('checkbox')
    expect(consent).not.toBeChecked()
    expect(consent.labels[0]).toHaveTextContent(
      /send the text details in this pack.*to the cyber cell queue.*screenshots are not sent.*stay on this device/i)
    expect(card().getByLabelText('NCRP acknowledgement number')).toHaveAccessibleDescription(/1930 or cybercrime\.gov\.in/)
  })

  it('needs the NCRP number, the consent and a pack with no problems before it sends', async () => {
    const server = fakeServer({ 'POST /api/complaints': SENT })
    const user = userEvent.setup()
    at()
    await send(user)
    expect(card().getByRole('alert')).toHaveTextContent('Give the NCRP acknowledgement number')
    expect(card().getByLabelText('NCRP acknowledgement number')).toHaveFocus()
    await fill(user, 'NCRP acknowledgement number', '12', card())
    await send(user)
    expect(card().getByRole('alert')).toHaveTextContent(/8 to 20 letters and digits/)
    await fill(user, 'NCRP acknowledgement number', '31234567890123', card())
    await send(user)
    expect(card().getByRole('alert')).toHaveTextContent(/Tick the box/)
    expect(card().getByRole('checkbox')).toHaveFocus()
    await agree(user)
    await fill(user, 'Your mobile number (optional)', '12345')
    await send(user)
    expect(card().getByRole('alert')).toHaveTextContent('Check the answer marked in red first.')
    expect(screen.getByLabelText('Your mobile number (optional)')).toHaveFocus()
    expect(server).not.toHaveBeenCalled()
  })

  it('sends only the text details, then shows the tracking code once with copy and print', async () => {
    const server = fakeServer({ 'POST /api/complaints': SENT })
    const user = userEvent.setup()
    at()
    await fill(user, 'Your name (optional)', 'Asha Rao')
    await fill(user, 'What happened, in your words', 'A mentor on Telegram showed me profits.')
    await fill(user, 'Transaction hash', HASH, payment(1))
    await fill(user, 'Amount', '2500', payment(1))
    await addPayment(user)
    await user.upload(shots(), new File(['private'], 'chat-1.png', { type: 'image/png' }))
    await fill(user, 'NCRP acknowledgement number', '31234567890123', card())
    await agree(user)
    await send(user)

    const receipt = within(await screen.findByRole('region', { name: /Write this code down/ }))
    expect(server.calls).toHaveLength(1)
    expect(server.calls[0].body).toEqual({
      ncrp: '31234567890123', name: 'Asha Rao', mobile: '', started: '', app: '', link: '', contacts: '', upi: '',
      story: 'A mentor on Telegram showed me profits.',
      payments: [{ hash: HASH, amount: '2500', token: '', network: '', paidAt: '', wallet: '' }],
    })
    expect(JSON.stringify(server.calls[0].body)).not.toMatch(/chat-1|files/)
    expect(receipt.getByText(CODE)).toBeInTheDocument()
    expect(receipt.getByText('EXQ-7KQ2M9PD')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /Write this code down/ }))
      .toHaveTextContent(/we cannot show it again/i)
    expect(screen.getByRole('heading', { name: /Write this code down/ })).toHaveFocus()
    await user.click(receipt.getByRole('button', { name: 'Copy the code' }))
    expect(await navigator.clipboard.readText()).toBe(CODE)
    expect(receipt.getByRole('status')).toHaveTextContent('Copied.')
    // Printing the code marks the page for it, so it prints the code alone,
    // until the print screen closes.
    let marked
    print.mockImplementation(() => { marked = document.documentElement.classList.contains('print-code') })
    await user.click(receipt.getByRole('button', { name: 'Print the code' }))
    expect(print).toHaveBeenCalledTimes(1)
    expect(marked).toBe(true)
    window.dispatchEvent(new Event('afterprint'))
    expect(document.documentElement).not.toHaveClass('print-code')
    expect(receipt.getByRole('link', { name: /My case/ })).toHaveAttribute('href', '/my-case')
    // Sent once: there is no second send, and the code is kept nowhere.
    expect(screen.queryByRole('button', { name: 'Send to the cyber cell queue' })).toBeNull()
    expect(sessionStorage.getItem(KEY) ?? '').not.toContain(CODE)
    expect(localStorage.length).toBe(0)
  })

  it('never prints the tracking code into the saved pack, which is given to others', async () => {
    fakeServer({ 'POST /api/complaints': SENT })
    const user = userEvent.setup()
    at()
    await fill(user, 'NCRP acknowledgement number', '31234567890123', card())
    await agree(user)
    await send(user)
    const receipt = within(await screen.findByRole('region', { name: /Write this code down/ }))
    // Even if the print screen of the code never said it closed.
    print.mockImplementation(() => {})
    await user.click(receipt.getByRole('button', { name: 'Print the code' }))
    let marked
    print.mockImplementation(() => { marked = document.documentElement.classList.contains('print-code') })
    await save(user)
    expect(print).toHaveBeenCalledTimes(2)
    expect(marked).toBe(false)
  })

  it('shows a sent pack as sent when the page is opened again, so it is not sent twice', async () => {
    const server = fakeServer({ 'POST /api/complaints': SENT })
    const user = userEvent.setup()
    const { unmount } = at()
    await fill(user, 'Your name (optional)', 'Asha Rao')
    await fill(user, 'NCRP acknowledgement number', '31234567890123', card())
    await agree(user)
    await send(user)
    await screen.findByRole('region', { name: /Write this code down/ })
    unmount()
    at()
    const sent = within(screen.getByRole('region', { name: 'Sent to the cyber cell queue' }))
    expect(sent.getByText('EXQ-7KQ2M9PD')).toBeInTheDocument()
    expect(sent.getByRole('link', { name: /My case/ })).toHaveAttribute('href', '/my-case')
    expect(screen.queryByRole('button', { name: 'Send to the cyber cell queue' })).toBeNull()
    expect(screen.getByRole('main')).not.toHaveTextContent(CODE)
    expect(sessionStorage.getItem(KEY)).not.toContain(CODE)
    expect(server.calls).toHaveLength(1)
    // A cleared form is a new pack, and can be sent.
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await user.click(screen.getByRole('button', { name: 'Clear this form' }))
    expect(card().getByRole('button', { name: 'Send to the cyber cell queue' })).toBeEnabled()
  })

  it.each([
    ['the number is full', [409, { error: 'This NCRP number already has as many complaints here as we can take.' }],
      /as many complaints here as we can take/],
    ['too many tries', [429, { error: 'Too many tries for now. Please try again later.' }, { 'Retry-After': '3600' }],
      /Too many tries for now.*in about an hour/],
    ['the server refuses a field', [400, { error: 'Payment 1: write the amount as a number.' }],
      /Payment 1: write the amount as a number\./],
    ['the site is down', [503, { error: 'This site cannot take requests right now. Please try again later.' }],
      /cannot take requests right now/],
    ['the site cannot be reached', OFFLINE, /could not reach the site/],
  ])('says so, and keeps the form, when %s', async (_, answer, said) => {
    fakeServer({ 'POST /api/complaints': answer })
    const user = userEvent.setup()
    at()
    await fill(user, 'Your name (optional)', 'Asha Rao')
    await fill(user, 'NCRP acknowledgement number', '31234567890123', card())
    await agree(user)
    await send(user)
    expect(await card().findByRole('alert')).toHaveTextContent(said)
    expect(card().getByRole('button', { name: 'Send to the cyber cell queue' })).toBeEnabled()
    expect(screen.getByLabelText('Your name (optional)')).toHaveValue('Asha Rao')
    expect(screen.queryByRole('region', { name: /Write this code down/ })).toBeNull()
  })

  it('passes the axe structural rules with the tracking code shown', async () => {
    fakeServer({ 'POST /api/complaints': SENT })
    const user = userEvent.setup()
    const { container } = at()
    await fill(user, 'NCRP acknowledgement number', '31234567890123', card())
    await agree(user)
    await send(user)
    await screen.findByRole('region', { name: /Write this code down/ })
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`)).toEqual([])
  })
})
