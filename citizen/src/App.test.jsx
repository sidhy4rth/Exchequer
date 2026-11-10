import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App.jsx'

const PAGES = {
  '/': 'Lost money? The first hours matter most.',
  '/right-now': 'Right now',
  '/report': 'Find your payment',
  '/report/pack': 'Your complaint pack',
  '/my-case': 'Track my complaint',
  '/learn': 'Know the scams',
  '/no-such-page': 'Page not found',
}

function at(path) {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
}

describe.each(Object.entries(PAGES))('%s', (path, title) => {
  it('renders its page in the landmarks, with one h1 and no skipped levels', () => {
    at(path)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(title)
    expect(document.title).toContain('Exchequer')
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByRole('contentinfo')).toBeInTheDocument()
    const levels = screen.getAllByRole('heading').map((h) => Number(h.tagName[1]))
    levels.forEach((level, i) => expect(level - (levels[i - 1] ?? 0)).toBeLessThanOrEqual(1))
  })

  it('shows both safety lines and says it is not an official site', () => {
    at(path)
    expect(screen.getByText('Police never charge a fee to recover money.')).toBeVisible()
    expect(screen.getByText('We never ask for your seed phrase or private key.')).toBeVisible()
    expect(screen.getByRole('contentinfo')).toHaveTextContent(/not a government or police site/i)
  })

  it('marks every list as a list, which Safari forgets when list-style is none', () => {
    const { container } = at(path)
    for (const list of container.querySelectorAll('ul, ol')) expect(list).toHaveAttribute('role', 'list')
  })

  it('links out only to the official portal, safely, and calls only 1930', () => {
    at(path)
    for (const link of screen.getAllByRole('link')) {
      const href = link.getAttribute('href')
      if (href.startsWith('tel:')) expect(href).toBe('tel:1930')
      else if (/^https?:/.test(href)) {
        expect(href).toBe('https://cybercrime.gov.in')
        expect(link).toHaveAttribute('target', '_blank')
        expect(link.getAttribute('rel').split(' ')).toEqual(expect.arrayContaining(['noopener', 'noreferrer']))
      } else expect(href).toMatch(/^\/|^#/)
    }
    const header = within(screen.getByRole('banner'))
    expect(header.getByRole('link', { name: /1930/ })).toHaveAttribute('href', 'tel:1930')
  })

  it('passes the axe structural rules (contrast is checked by hand)', async () => {
    const { container } = at(path)
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`)).toEqual([])
  })
})

describe('home', () => {
  it('puts Call 1930 and the reporting portal first', () => {
    at('/')
    const hero = within(screen.getByRole('heading', { level: 1 }).closest('section'))
    expect(hero.getByRole('link', { name: /Call 1930/ })).toHaveAttribute('href', 'tel:1930')
    const portal = hero.getByRole('link', { name: /Report at cybercrime\.gov\.in/ })
    expect(portal).toHaveAttribute('href', 'https://cybercrime.gov.in')
  })

  it('offers the three next steps', () => {
    at('/')
    expect(screen.getByRole('link', { name: /What to do right now/ })).toHaveAttribute('href', '/right-now')
    expect(screen.getByRole('link', { name: /Find your payment/ })).toHaveAttribute('href', '/report')
    expect(screen.getByRole('link', { name: /Track my complaint/ })).toHaveAttribute('href', '/my-case')
  })
})

describe('right now', () => {
  it('lists three things to do and three not to do', () => {
    at('/right-now')
    const dos = within(screen.getByRole('list', { name: 'Do' })).getAllByRole('listitem')
    const donts = within(screen.getByRole('list', { name: "Don't" })).getAllByRole('listitem')
    expect(dos.map((li) => li.textContent)).toEqual([
      expect.stringMatching(/Call 1930/), expect.stringMatching(/evidence.*UPI IDs.*wallet addresses/s),
      expect.stringMatching(/payment hash/)])
    expect(donts.map((li) => li.textContent)).toEqual([
      expect.stringMatching(/send more money.*fee/is), expect.stringMatching(/recovery agent/),
      expect.stringMatching(/delete the chats or the app/i)])
  })

  it('warns off recovery offers without ruling out a lawyer the victim hires', () => {
    at('/right-now')
    const item = within(screen.getByRole('list', { name: "Don't" })).getByText(/recovery agent/).closest('li')
    expect(item).toHaveTextContent(/contacts you.*get your money back.*fee.*second scam/i)
    expect(item).toHaveTextContent('Police never charge.')
    expect(item).not.toHaveTextContent(/anyone who asks for money/i)
  })
})

describe('coming soon pages', () => {
  it('/my-case says it is not switched on and where to report meanwhile', () => {
    at('/my-case')
    const main = within(screen.getByRole('main'))
    expect(main.getByText(/not switched on yet/)).toBeInTheDocument()
    expect(main.getByRole('link', { name: /Call 1930/ })).toHaveAttribute('href', 'tel:1930')
    expect(main.getByRole('link', { name: /cybercrime\.gov\.in/ })).toHaveAttribute('href', 'https://cybercrime.gov.in')
  })
})

describe('navigation', () => {
  it('moves between the tabs and marks the current one', async () => {
    const user = userEvent.setup()
    at('/')
    const nav = within(screen.getByRole('navigation', { name: 'Main' }))
    expect(nav.getByRole('link', { name: 'Home' })).toHaveAttribute('aria-current', 'page')
    for (const [tab, title] of [['Report', 'Find your payment'], ['My case', 'Track my complaint'],
      ['Learn', 'Know the scams'], ['Home', 'Lost money?']]) {
      await user.click(nav.getByRole('link', { name: tab }))
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(title)
      expect(nav.getByRole('link', { name: tab })).toHaveAttribute('aria-current', 'page')
      expect(screen.getByRole('main')).toHaveFocus()
    }
  })

  it('goes from home to the right-now steps and back', async () => {
    const user = userEvent.setup()
    at('/')
    await user.click(screen.getByRole('link', { name: /What to do right now/ }))
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Right now')
    await user.click(screen.getByRole('link', { name: 'Back to home' }))
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Lost money?')
  })
})

describe('learn', () => {
  it('describes five common scams, each with 3-4 warning signs and what to do', () => {
    at('/learn')
    const cards = screen.getAllByRole('article')
    expect(cards.map((card) => within(card).getByRole('heading', { level: 2 }).textContent)).toEqual([
      expect.stringMatching(/trading.*cannot lose/i), expect.stringMatching(/tasks.*deposits/i),
      expect.stringMatching(/friend.*invest/i), expect.stringMatching(/customer care.*recovery/i),
      expect.stringMatching(/police, customs or courier.*digital arrest/i)])
    for (const card of cards) {
      const signs = within(within(card).getByRole('list', { name: /warning signs/i })).getAllByRole('listitem')
      expect(signs.length).toBeGreaterThanOrEqual(3)
      expect(signs.length).toBeLessThanOrEqual(4)
      expect(within(card).getByText('What to do:').parentElement.textContent).toMatch(/^What to do: \S.{30,}\.$/)
    }
  })

  it('names the signs each scam is known for', () => {
    at('/learn')
    const [invest, tasks, friend, helpers, arrest] = screen.getAllByRole('article')
    expect(invest).toHaveTextContent(/guaranteed.*cannot withdraw.*fee/is)
    expect(tasks).toHaveTextContent(/like videos or rate hotels.*USDT deposit/is)
    expect(friend).toHaveTextContent(/met online.*trading/is)
    expect(helpers).toHaveTextContent(/screen-sharing.*seed phrase.*recovery for a fee/is)
    expect(helpers).toHaveTextContent(/Never pay anyone to recover money/)
    expect(arrest).toHaveTextContent(/video call.*stay on the call.*clear your name/is)
    expect(arrest).toHaveTextContent(/Hang up and call 1930/)
  })

  it('stays calm, and points someone who already paid to what to do now', () => {
    at('/learn')
    expect(screen.getByRole('main').textContent).not.toMatch(/!/)
    expect(screen.getByRole('heading', { level: 2, name: 'Already paid?' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /What to do right now/ })).toHaveAttribute('href', '/right-now')
  })
})

describe('find your payment', () => {
  const HASH = 'fde547813899a616a09c79842f0a413ac561505e0baa6db6b11f910a34a02e8e'
  afterEach(() => vi.unstubAllGlobals())

  async function check(user, text) {
    const box = screen.getByLabelText('Paste it here')
    await user.clear(box)
    if (text) {
      await user.click(box)
      await user.paste(text)
    }
    await user.click(screen.getByRole('button', { name: /Check this hash/ }))
    return screen.getByRole('status')
  }

  it('is step 1 of 3, with the complaint pack a link and confirming still to come', () => {
    at('/report')
    const steps = within(screen.getByRole('list', { name: 'Report steps' })).getAllByRole('listitem')
    expect(steps).toHaveLength(3)
    expect(steps[0]).toHaveAttribute('aria-current', 'step')
    expect(steps[0]).toHaveTextContent('Find your payment')
    expect(steps[1]).toHaveTextContent(/Confirm it.*coming later/)
    expect(within(steps[2]).getByRole('link', { name: /Complaint pack/ })).toHaveAttribute('href', '/report/pack')
    expect(steps[2]).not.toHaveTextContent(/coming later/)
  })

  it('shows where to find the hash in each kind of app, naming none', async () => {
    const user = userEvent.setup()
    at('/report')
    const group = within(screen.getByRole('group', { name: 'Where did you send the money from?' }))
    expect(group.getAllByRole('radio').map((radio) => radio.labels[0].textContent))
      .toEqual(['Exchange app', 'Wallet app', 'Browser wallet'])
    const steps = () => within(screen.getByRole('list', { name: 'Where to find the transaction hash' }))
      .getAllByRole('listitem').map((li) => li.textContent)
    expect(group.getByRole('radio', { name: 'Exchange app' })).toBeChecked()
    expect(steps()).toEqual([expect.stringMatching(/withdrawal/i), expect.stringMatching(/payment/),
      expect.stringMatching(/Transaction ID, TxID or Hash/)])
    await user.click(group.getByRole('radio', { name: 'Wallet app' }))
    expect(steps()).toEqual([expect.stringMatching(/coin you sent/), expect.stringMatching(/payment/),
      expect.stringMatching(/block explorer/)])
    await user.click(group.getByRole('radio', { name: 'Browser wallet' }))
    expect(steps()[0]).toMatch(/Activity/)
    expect(screen.getByRole('main').textContent)
      .not.toMatch(/binance|wazirx|coindcx|coinbase|bybit|okx|kucoin|metamask|trust wallet|tronlink|phantom/i)
  })

  it('checks a pasted hash on the device and names the networks it could be on', async () => {
    const network = vi.fn()
    vi.stubGlobal('fetch', network)
    vi.stubGlobal('XMLHttpRequest', network)
    const user = userEvent.setup()
    at('/report')
    const status = await check(user, `  ${HASH.slice(0, 40)}\n${HASH.slice(40)} `)
    expect(status).toHaveTextContent('This has the shape of a transaction hash.')
    expect(within(status).getByText(HASH).tagName).toBe('CODE')
    expect(status).toHaveTextContent(/payment on Tron, Ethereum, BNB Smart Chain, Polygon,? or Arbitrum\./)
    expect(screen.getByLabelText('Paste it here')).not.toHaveAttribute('aria-invalid')
    const evm = await check(user, `0x${HASH}`)
    // TRC20 stays among the labels that "say which", so Tron stays on the list.
    expect(evm).toHaveTextContent(/payment on Ethereum, BNB Smart Chain, Polygon, Arbitrum,? or Tron\..*TRC20/)
    expect(network).not.toHaveBeenCalled()
  })

  it('takes the hash out of a link or a label pasted with it, and says so', async () => {
    const user = userEvent.setup()
    at('/report')
    const status = await check(user, `https://tronscan.org/#/transaction/${HASH}`)
    expect(status).toHaveTextContent(/This has the shape of a transaction hash\..*found it inside/)
    expect(within(status).getByText(HASH).tagName).toBe('CODE')
    expect(await check(user, HASH)).not.toHaveTextContent(/found it inside/)
  })

  it('warns that a private key looks the same and must never be shared', async () => {
    const user = userEvent.setup()
    at('/report')
    const box = screen.getByLabelText('Paste it here')
    expect(box).toHaveAccessibleDescription(/hash is safe to share.*private key or a seed phrase is not.*never/i)
    const status = await check(user, HASH)
    expect(status).toHaveTextContent(/A private key looks the same\..*do not share it with anyone\./)
    expect(status).toHaveTextContent(/If you copied it from the payment's details, keep it with your evidence/)
  })

  it('asks for a hash, without an error, when the box is empty', async () => {
    const user = userEvent.setup()
    at('/report')
    const status = await check(user, '')
    expect(status).toHaveTextContent(/^Paste the hash in the box first\.$/)
    expect(screen.getByLabelText('Paste it here')).not.toHaveAttribute('aria-invalid')
  })

  it('explains what is wrong with something that is not a hash, and forgets it on a new paste', async () => {
    const user = userEvent.setup()
    at('/report')
    const box = screen.getByLabelText('Paste it here')
    expect(await check(user, 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t')).toHaveTextContent(/wallet address, not a payment/)
    expect(box).toHaveAttribute('aria-invalid', 'true')
    expect(await check(user, HASH.slice(3))).toHaveTextContent(/61 characters.*64/)
    const chars = await check(user, `TxID: ${HASH.slice(1)}`)
    expect(chars).toHaveTextContent(/0 to 9 and the letters a to f.*without the words or link around it/)
    // It cannot know what was pasted, so it does not say it is an order ID.
    expect(chars).not.toHaveTextContent(/may be another number/)
    await user.type(box, '1')
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
    expect(box).not.toHaveAttribute('aria-invalid')
  })

  it('never calls a hash from another network wrong, nor says the payment can only be on these', async () => {
    const user = userEvent.setup()
    at('/report')
    // A Solana signature: 88 base58 characters.
    const solana = await check(user, `5Ur${'QkRmVxyz'.repeat(10)}abcde`)
    expect(solana).not.toHaveTextContent(/does not look like a transaction hash/)
    expect(solana).toHaveTextContent(/not the shape of a Tron or Ethereum-style hash/)
    expect(solana).toHaveTextContent(/On Tron, Ethereum and the other networks this site checks, a hash has only/)
    expect(solana).toHaveTextContent(/another network, such as Bitcoin or Solana, .*keep the hash as you copied it/)
    expect(await check(user, HASH.slice(3))).toHaveTextContent(/another network, such as Bitcoin or Solana/)
    // A Bitcoin txid has the same 64-character shape.
    const bitcoin = await check(user, HASH)
    expect(bitcoin).toHaveTextContent(/On the networks this site checks, it could be a payment on Tron/)
    expect(bitcoin).toHaveTextContent(/A hash from another network, such as Bitcoin, can look the same\./)
  })

  it('says it sends nothing, and that confirming the payment and searching by amount come later', async () => {
    const user = userEvent.setup()
    at('/report')
    const main = screen.getByRole('main')
    expect(main).toHaveTextContent(/runs on your device and sends nothing/)
    expect(main).toHaveTextContent(
      'Confirming the payment on the blockchain will be switched on later.')
    expect(main).not.toHaveTextContent(/later, with the complaint pack/)
    const fallback = screen.getByText(/Search by amount and date/).closest('details')
    await user.click(screen.getByText(/Search by amount and date/))
    expect(fallback).toHaveAttribute('open')
    expect(fallback).toHaveTextContent(/coming later.*wallet you paid.*amount.*date/is)
  })

  it('passes the axe structural rules with a verdict shown and the fallback open', async () => {
    const user = userEvent.setup()
    const { container } = at('/report')
    await check(user, 'abc')
    await user.click(screen.getByText(/Search by amount and date/))
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(' ')}`)).toEqual([])
  })
})
