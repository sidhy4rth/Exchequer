import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App.jsx'

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
  it('is step 3 of 3, with step 1 a link back and step 2 still to come', () => {
    at()
    const steps = within(screen.getByRole('list', { name: 'Report steps' })).getAllByRole('listitem')
    expect(steps[2]).toHaveAttribute('aria-current', 'step')
    expect(within(steps[0]).getByRole('link', { name: /Find your payment/ })).toHaveAttribute('href', '/report')
    expect(steps[1]).toHaveTextContent(/Confirm it.*coming later/)
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
    expect(screen.getByRole('main')).toHaveTextContent(/Nothing you type here is sent anywhere/)
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
