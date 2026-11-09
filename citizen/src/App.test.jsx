import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from './App.jsx'

const PAGES = {
  '/': 'Lost money? The first hours matter most.',
  '/right-now': 'Right now',
  '/report': 'Find your payment',
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
  it.each(['/report', '/my-case'])('%s says it is not switched on and where to report meanwhile', (path) => {
    at(path)
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
