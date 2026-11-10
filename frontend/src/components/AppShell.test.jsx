import { act, cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import AppShell, { ADMIN_GROUP, GROUPS, useCrumb } from './AppShell'
import { signedInAs } from '../session'
import { stubFetch } from '../test/setup'
import { ALL_CHAINS_READY } from '../../e2e/canary.lines.js'
import canarySource from '../../e2e/canary.spec.js?raw'

const chains = {
  status: 'ok',
  default_chain: 'ethereum',
  chains: {
    ethereum: { key: 'ethereum', name: 'Ethereum', ready: true, address_family: 'evm', assets: [{ symbol: 'ETH' }],
      risk_labels: { sanctioned: 127, mixer: 0, frozen: 2828, stolen: 11 } },
    tron: { key: 'tron', name: 'Tron', ready: false, address_family: 'tron', assets: [{ symbol: 'TRX' }, { symbol: 'USDT' }],
      risk_labels: { sanctioned: 915, mixer: 0, frozen: 6759, stolen: 0 } },
  },
}

function Landed() {
  const { pathname, search } = useLocation()
  return <p data-testid="landed">{pathname + search}</p>
}

function at(path, health = chains) {
  stubFetch({ '/chains': { body: health } })
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="*" element={<Landed />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

const sidebar = () => within(screen.getByRole('complementary', { name: 'Sidebar' }))
const phoneBar = () => within(screen.getByRole('navigation', { name: 'Sections' }))

describe('the sidebar', () => {
  it('groups every page under Investigate, Monitor and Evidence', () => {
    at('/')
    const nav = within(sidebar().getByRole('navigation', { name: 'Main' }))
    const group = (name) => within(nav.getByRole('list', { name })).getAllByRole('link').map((a) => [a.textContent, a.getAttribute('href')])
    expect(group('Investigate')).toEqual([['Console', '/'], ['New trace', '/trace/new'], ['Cases', '/cases'], ['Bulk intake', '/batch']])
    expect(group('Monitor')).toEqual([['Watchlist', '/watchlist'], ['Requests', '/requests'], ['Complaints', '/complaints']])
    expect(group('Evidence')).toEqual([['Verify a report', '/verify']])
    expect(GROUPS.map(([name]) => name)).toEqual(['Investigate', 'Monitor', 'Evidence'])
  })

  it('says it is a demo, seen as an investigator, under the name', () => {
    at('/')
    expect(sidebar().getByRole('link', { name: 'Exchequer' })).toHaveAttribute('href', '/')
    expect(sidebar().getByText('Demo mode · Investigator')).toBeInTheDocument()
    expect(sidebar().getByRole('button', { name: 'Switch to citizen view' })).toBeInTheDocument()
    expect(sidebar().getByRole('button', { name: 'Leave' })).toBeInTheDocument()
  })

  it('marks the page you are on, and the section a case sits in', () => {
    const { unmount } = at('/cases')
    const link = (name) => sidebar().getByRole('link', { name })
    expect(link('Cases')).toHaveAttribute('aria-current', 'page')
    expect(link('Console')).not.toHaveAttribute('aria-current')
    unmount()
    at('/case/3f2504e0-4f89-41d3-9a0c-0305e82c3301')
    expect(link('Cases')).toHaveAttribute('aria-current', 'true')
    const crumbs = within(screen.getByRole('navigation', { name: 'Breadcrumb' }))
    expect(crumbs.getByRole('link', { name: 'Cases' })).toHaveAttribute('href', '/cases')
    expect(crumbs.getByText(/^3f2504e0/)).toHaveAttribute('aria-current', 'page')
  })

  it('names a recorded example and a trace link in the breadcrumbs', () => {
    const { unmount } = at('/demo/11')
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('Cases/Verified example 11')
    unmount()
    at(`/trace/0x${'ab'.repeat(20)}?chain=ethereum`)
    expect(sidebar().getByRole('link', { name: 'New trace' })).toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent(/^New trace\/0xabababab/)
  })

  it('names a case by its address once the page knows it', () => {
    function Named() {
      useCrumb('TUVNGw2z3G…Krve5i3ts')
      return null
    }
    stubFetch({ '/chains': { body: chains } })
    render(
      <MemoryRouter initialEntries={['/demo/11']}>
        <Routes><Route element={<AppShell />}><Route path="*" element={<Named />} /></Route></Routes>
      </MemoryRouter>,
    )
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(crumbs).toHaveTextContent(/^Cases\/TUVNGw2z3G…Krve5i3ts$/)
    expect(within(crumbs).getByText('TUVNGw2z3G…Krve5i3ts')).toHaveAttribute('aria-current', 'page')
  })

  it('reads a path with a trailing slash as the same page', () => {
    const { unmount } = at('/batch/')
    expect(sidebar().getByRole('link', { name: 'Bulk intake' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent(/^Bulk intake$/)
    unmount()
    at('/cases/')
    expect(sidebar().getByRole('link', { name: 'Cases' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent(/^Cases$/)
  })

  it('says how many chains can trace and what is screened, from /chains, and nothing it cannot know', async () => {
    at('/')
    expect(await sidebar().findByText('1 of 2 chains ready to trace')).toBeInTheDocument()
    // Only a chain that traces screens anything: Tron's 7,674 are not counted
    // while it is off, and no hop is screened against another chain's list.
    expect(sidebar().getByText('3K flagged addresses on file for screening')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/nightly|refresh|every hop/i)
  })

  it('counts one chain as one chain, and all of them as all', async () => {
    const one = { status: 'ok', chains: { ethereum: { ...chains.chains.ethereum } } }
    const { unmount } = at('/', one)
    expect(await sidebar().findByText('1 of 1 chain ready to trace')).toBeInTheDocument()
    unmount()
    at('/', { ...chains, chains: { ...chains.chains, tron: { ...chains.chains.tron, ready: true } } })
    expect(await sidebar().findByText('All 2 chains ready to trace')).toBeInTheDocument()
    expect(sidebar().getByText('10.6K flagged addresses on file for screening')).toBeInTheDocument()
  })

  it('says what the site canary looks for once every chain is ready', async () => {
    at('/', { ...chains, chains: { ...chains.chains, tron: { ...chains.chains.tron, ready: true } } })
    expect(await sidebar().findByText(ALL_CHAINS_READY)).toBeInTheDocument()
    expect(canarySource).toContain('getByText(ALL_CHAINS_READY)')
    expect(canarySource).not.toMatch(/Live ·/)
  })

  it('says so when the backend cannot be reached', async () => {
    stubFetch({})
    render(<MemoryRouter><Routes><Route element={<AppShell />}><Route path="*" element={<Landed />} /></Route></Routes></MemoryRouter>)
    expect(await sidebar().findByText('Backend unreachable')).toBeInTheDocument()
  })

  // One miss (a restart, a 502 from the proxy) must not last the session.
  const flaky = (misses) => {
    let calls = 0
    return vi.fn(() => (++calls <= misses ? { status: 502, body: 'Bad gateway' } : { body: chains }))
  }

  it('asks again on its own after the backend could not be reached, and says when it is back', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const answer = flaky(1)
      stubFetch({ '/chains': answer })
      render(<MemoryRouter><Routes><Route element={<AppShell />}><Route path="*" element={<Landed />} /></Route></Routes></MemoryRouter>)
      expect(await sidebar().findByText('Backend unreachable')).toBeInTheDocument()
      await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
      expect(await sidebar().findByText('1 of 2 chains ready to trace')).toBeInTheDocument()
      expect(answer).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('asks again when you open another page while the backend is unreachable', async () => {
    const user = userEvent.setup()
    stubFetch({ '/chains': flaky(1) })
    render(<MemoryRouter><Routes><Route element={<AppShell />}><Route path="*" element={<Landed />} /></Route></Routes></MemoryRouter>)
    expect(await sidebar().findByText('Backend unreachable')).toBeInTheDocument()
    await user.click(sidebar().getByRole('link', { name: 'Cases' }))
    expect(await sidebar().findByText('1 of 2 chains ready to trace')).toBeInTheDocument()
  })
})

describe('the header search', () => {
  async function search(text) {
    const user = userEvent.setup()
    at('/')
    await sidebar().findByText(/chains ready/)
    const box = within(screen.getByRole('search')).getByRole('searchbox', { name: 'Wallet, transaction hash or case ID' })
    await user.type(box, `${text}{Enter}`)
    return box
  }

  it('opens a wallet at its trace link, which asks before it runs', async () => {
    const wallet = `0x${'ab'.repeat(20)}`
    await search(wallet)
    expect(screen.getByTestId('landed')).toHaveTextContent(`/trace/${wallet}?chain=ethereum&asset=ETH`)
  })

  it('takes a transaction hash to a new trace with the hash filled in', async () => {
    await search(`0x${'e'.repeat(64)}`)
    expect(screen.getByTestId('landed')).toHaveTextContent(`/trace/new?pay=0x${'e'.repeat(64)}`)
  })

  it('opens a case by its id', async () => {
    await search('3f2504e0-4f89-41d3-9a0c-0305e82c3301')
    expect(screen.getByTestId('landed')).toHaveTextContent('/case/3f2504e0-4f89-41d3-9a0c-0305e82c3301')
  })

  it('says, in place, when it does not recognise the text', async () => {
    const user = userEvent.setup()
    const box = await search('binance hot wallet')
    expect(screen.getByTestId('landed')).toHaveTextContent(/^\/$/)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent(/not recognised/i)
    expect(box).toHaveAttribute('aria-invalid', 'true')
    expect(box).toHaveAccessibleDescription(alert.textContent)
    await user.type(box, 'x')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('takes the not-recognised note away on another page, on Escape and when focus leaves', async () => {
    const user = userEvent.setup()
    const box = await search('abc')
    expect(screen.getByRole('alert')).toBeInTheDocument()
    await user.click(sidebar().getByRole('link', { name: 'Cases' }))
    expect(screen.getByTestId('landed')).toHaveTextContent(/^\/cases$/)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(box).not.toHaveAttribute('aria-invalid')

    await user.type(box, 'abc{Enter}')
    expect(screen.getByRole('alert')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await user.clear(box)
    await user.type(box, 'abc{Enter}')
    expect(screen.getByRole('alert')).toBeInTheDocument()
    await user.tab()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('the page title', () => {
  it('names the page, and a case by what is open inside it', async () => {
    const user = userEvent.setup()
    const first = document.title
    at('/cases')
    expect(document.title).toBe('Cases · Exchequer')
    await user.click(sidebar().getByRole('link', { name: 'Watchlist' }))
    expect(document.title).toBe('Watchlist · Exchequer')
    await user.click(sidebar().getByRole('link', { name: 'Console' }))
    expect(document.title).toBe('Console · Exchequer')
    cleanup()
    expect(document.title).toBe(first)
    at('/demo/11')
    expect(document.title).toBe('Verified example 11 · Cases · Exchequer')
  })

  it('uses the address a case page names once it knows it', () => {
    function Named() {
      useCrumb('TUVNGw2z3G…Krve5i3ts')
      return null
    }
    stubFetch({ '/chains': { body: chains } })
    render(
      <MemoryRouter initialEntries={['/case/3f2504e0-4f89-41d3-9a0c-0305e82c3301']}>
        <Routes><Route element={<AppShell />}><Route path="*" element={<Named />} /></Route></Routes>
      </MemoryRouter>,
    )
    expect(document.title).toBe('TUVNGw2z3G…Krve5i3ts · Cases · Exchequer')
  })
})

describe('the phone tab bar', () => {
  it('holds Console, New trace, Cases, Watchlist, and More for the rest', async () => {
    const user = userEvent.setup()
    at('/requests')
    const bar = phoneBar()
    expect(bar.getAllByRole('link').map((a) => a.textContent)).toEqual(['Console', 'New trace', 'Cases', 'Watchlist'])
    const more = bar.getByRole('button', { name: 'More' })
    expect(more).toHaveAttribute('aria-expanded', 'false')
    await user.click(more)
    expect(more).toHaveAttribute('aria-expanded', 'true')
    const menu = within(document.getElementById(more.getAttribute('aria-controls')))
    expect(menu.getAllByRole('link').map((a) => a.textContent)).toEqual(['Bulk intake', 'Requests', 'Complaints', 'Verify a report'])
    expect(menu.getByRole('link', { name: 'Requests' })).toHaveAttribute('aria-current', 'page')
    expect(menu.getByRole('button', { name: 'Switch to citizen view' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(more).toHaveAttribute('aria-expanded', 'false')
    expect(more).toHaveFocus()
  })

  it('puts the menu next in the Tab order after More, and closes it when focus moves on', async () => {
    const user = userEvent.setup()
    at('/')
    const more = phoneBar().getByRole('button', { name: 'More' })
    await user.click(more)
    await user.tab()
    expect(phoneBar().getByRole('link', { name: 'Bulk intake' })).toHaveFocus()
    // Escape from inside the menu closes it and goes back to More.
    await user.keyboard('{Escape}')
    expect(more).toHaveAttribute('aria-expanded', 'false')
    expect(more).toHaveFocus()
    // Focus leaving the bar for the page closes the menu, so it never sits
    // over the control that now has focus.
    await user.click(more)
    act(() => screen.getByRole('searchbox').focus())
    expect(more).toHaveAttribute('aria-expanded', 'false')
    // As does a press anywhere outside it.
    await user.click(more)
    await user.click(screen.getByTestId('landed'))
    expect(more).toHaveAttribute('aria-expanded', 'false')
  })

  it('closes More once a page is chosen', async () => {
    const user = userEvent.setup()
    at('/')
    await user.click(phoneBar().getByRole('button', { name: 'More' }))
    await user.click(phoneBar().getByRole('link', { name: 'Bulk intake' }))
    expect(screen.getByTestId('landed')).toHaveTextContent('/batch')
    expect(phoneBar().getByRole('button', { name: 'More' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('lets the keyboard skip straight to the page', () => {
    at('/')
    const skip = screen.getByRole('link', { name: 'Skip to the page' })
    expect(skip).toHaveAttribute('href', '#main')
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main')
  })
})

describe('signed in as an officer', () => {
  const asha = { id: 3, name: 'Asha Rao', email: 'asha@cell.in', role: 'officer', unit: { id: 1, name: 'Bengaluru CEN' }, active: true, must_change_password: false }

  it('names the officer and their unit with Sign out, in place of the demo line', () => {
    signedInAs(asha)
    at('/')
    expect(sidebar().getByText('Asha Rao')).toBeInTheDocument()
    expect(sidebar().getByText('Bengaluru CEN')).toBeInTheDocument()
    expect(sidebar().getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
    expect(sidebar().queryByText(/Demo mode/)).toBeNull()
    expect(sidebar().queryByRole('button', { name: /switch to/i })).toBeNull()
    expect(sidebar().queryByRole('list', { name: 'Admin' })).toBeNull()
  })

  it("gives an admin the Admin group, and the phone's More menu its page and Sign out", async () => {
    const user = userEvent.setup()
    signedInAs({ ...asha, role: ['ad', 'min'].join('') })
    at('/')
    expect(ADMIN_GROUP[0]).toBe('Admin')
    expect(within(sidebar().getByRole('list', { name: 'Admin' })).getAllByRole('link').map((a) => [a.textContent, a.getAttribute('href')])).toEqual([['Admin', '/admin']])
    await user.click(phoneBar().getByRole('button', { name: 'More' }))
    const menu = within(document.getElementById('shell-more'))
    expect(menu.getAllByRole('link').map((a) => a.textContent)).toEqual(['Bulk intake', 'Requests', 'Complaints', 'Verify a report', 'Admin'])
    expect(menu.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
    expect(menu.queryByRole('button', { name: /switch to/i })).toBeNull()
  })
})

describe('the sidebar in motion', () => {
  const order = GROUPS.flatMap(([, items]) => items).map((i) => i.to)
  /** Lays the sidebar out as a browser would: each link 40 px tall, 44 px apart. */
  function laidOut() {
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function height() {
      return this.classList?.contains('shell-link') ? 40 : 0
    })
    // Measured from the nav's box (getBoundingClientRect), as a browser lays
    // it out: the nav starts 100 px down the page. offsetTop is left lying
    // (0, as Gecko reports it while each <li> is mid-slide) so a pill placed
    // from it would sit on the wrong page.
    vi.spyOn(HTMLElement.prototype, 'offsetTop', 'get').mockImplementation(() => 0)
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function box() {
      const top = this.classList?.contains('shell-link') ? 100 + order.indexOf(this.getAttribute('href')) * 44
        : this.classList?.contains('shell-nav') ? 100 : 0
      return { top, bottom: top + 40, left: 0, right: 0, width: 0, height: 40, x: 0, y: top, toJSON() {} }
    })
  }
  /** The screen asks for reduced motion (or not). */
  function stillness(still) {
    vi.stubGlobal('matchMedia', (query) => ({
      matches: still && query.includes('prefers-reduced-motion'), media: query,
      addEventListener() {}, removeEventListener() {},
    }))
  }
  const pill = () => document.querySelector('.shell-nav .shell-pill')

  it('opens with the sidebar sliding in, a sheen and its pages staggered 60 ms apart, at most 8 steps', () => {
    signedInAs({ id: 3, name: 'Asha Rao', email: 'a@cell.in', role: ['ad', 'min'].join(''), unit: { id: 1, name: 'CEN' }, active: true, must_change_password: false })
    at('/')
    const side = screen.getByRole('complementary', { name: 'Sidebar' })
    expect(side).toHaveClass('intro')
    expect(side.querySelector('.shell-sheen')).toHaveAttribute('aria-hidden', 'true')
    const steps = [...side.querySelectorAll('.shell-nav li')].map((li) => li.style.getPropertyValue('--i'))
    expect(steps).toEqual(['0', '1', '2', '3', '4', '5', '6', '7', '8'])
  })

  it('plays the opening once: its classes come off and a new page does not replay it', async () => {
    vi.useFakeTimers()
    try {
      laidOut()
      at('/')
      const side = screen.getByRole('complementary', { name: 'Sidebar' })
      expect(side).toHaveClass('intro')
      act(() => { vi.advanceTimersByTime(3000) })
      expect(side).not.toHaveClass('intro')
      expect(side.querySelector('.shell-sheen')).toBeNull()
      act(() => { within(side).getByRole('link', { name: 'Cases' }).click() })
      expect(side).not.toHaveClass('intro')
      expect(side.querySelector('.shell-nav li').style.getPropertyValue('--i')).toBe('')
    } finally {
      vi.useRealTimers()
    }
  })

  it('sits a pill behind the page you are on, and glides it to the next page', async () => {
    const user = userEvent.setup()
    laidOut()
    at('/cases')
    expect(pill()).toHaveAttribute('aria-hidden', 'true')
    expect(pill()).toHaveAttribute('data-on', '/cases')
    expect(pill().style.transform).toBe('translateY(88px)')
    expect(pill().style.height).toBe('40px')
    expect(pill()).not.toHaveClass('glide') // placed, not flown in from the top
    expect(screen.getByRole('navigation', { name: 'Main' })).toHaveClass('has-pill')
    await user.click(sidebar().getByRole('link', { name: 'Watchlist' }))
    expect(pill()).toHaveAttribute('data-on', '/watchlist')
    expect(pill().style.transform).toBe(`translateY(${order.indexOf('/watchlist') * 44}px)`)
    expect(pill()).toHaveClass('glide')
  })

  it('sits behind the section a case is inside, too', () => {
    laidOut()
    at('/case/3f2504e0-4f89-41d3-9a0c-0305e82c3301')
    expect(pill()).toHaveAttribute('data-on', '/cases')
  })

  it('leaves the current link its own fill when there is nothing laid out to measure (a phone)', () => {
    at('/cases')
    expect(pill()).toBeNull()
    expect(screen.getByRole('navigation', { name: 'Main' })).not.toHaveClass('has-pill')
    expect(sidebar().getByRole('link', { name: 'Cases' })).toHaveAttribute('aria-current', 'page')
  })

  it('stays still under reduced motion: no slide, no sheen, no stagger, and the pill jumps', async () => {
    const user = userEvent.setup()
    stillness(true)
    laidOut()
    at('/cases')
    const side = screen.getByRole('complementary', { name: 'Sidebar' })
    expect(side).not.toHaveClass('intro')
    expect(side.querySelector('.shell-sheen')).toBeNull()
    expect([...side.querySelectorAll('.shell-nav li')].every((li) => li.getAttribute('style') === null)).toBe(true)
    expect(pill()).toHaveAttribute('data-on', '/cases')
    await user.click(sidebar().getByRole('link', { name: 'Watchlist' }))
    expect(pill()).toHaveAttribute('data-on', '/watchlist')
    expect(pill()).not.toHaveClass('glide')
  })
})

describe('the motion tokens', () => {
  const css = readFileSync(resolve(__dirname, '../styles.css'), 'utf8')
  const shellCss = readFileSync(resolve(__dirname, 'AppShell.css'), 'utf8')
  const root = css.slice(css.indexOf(':root {'), css.indexOf('}', css.indexOf(':root {')))

  it.each([
    ['--ease-enter', 'cubic-bezier(0.22, 1, 0.36, 1)'],
    ['--ease-move', 'cubic-bezier(0.45, 0, 0.2, 1)'],
    ['--ease-pop', 'cubic-bezier(0.34, 1.56, 0.64, 1)'],
    ['--dur-hover', 'var(--fast)'],
    ['--dur-tab', '240ms'],
    ['--dur-pop', '450ms'],
    ['--dur-enter', '600ms'],
    ['--dur-route', '1400ms'],
    ['--stagger', '60ms'],
  ])('defines %s as %s on the root, for both skins', (name, value) => {
    expect(root).toContain(`${name}: ${value};`)
  })

  it('turns the opening, the sheen and the glide off under reduced motion, and the slide off on a phone', () => {
    const still = /@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/.exec(shellCss)[1]
    expect(still).toMatch(/\.shell-side\.intro[^{]*\{ animation: none; \}/)
    expect(still).toMatch(/\.shell-pill\.glide \{ transition: none; \}/)
    expect(still).toMatch(/\.shell-sheen \{ display: none; \}/)
    const phone = /@media \(max-width: 720px\) \{([\s\S]*)\n\}/.exec(shellCss)[1]
    expect(phone).toMatch(/\.shell-side\.intro \{ animation: none; \}/)
  })

  it('slides the links, not their <li>s, and keeps the pill under the group headings', () => {
    // A transformed <li> would become the link's offsetParent in some engines.
    expect(shellCss).toMatch(/\.shell-side\.intro \.shell-nav \.shell-link \{\s*animation: shell-slide/)
    expect(shellCss).not.toMatch(/\.shell-side\.intro \.shell-nav li \{/)
    expect(shellCss).toMatch(/\.shell-nav \{[^}]*isolation: isolate/)
    expect(shellCss).toMatch(/\.shell-pill \{[^}]*z-index: 0/)
    expect(shellCss).toMatch(/\.shell-nav > :not\(\.shell-pill\) \{ position: relative; z-index: 1; \}/)
  })

  it('marks the current page with a bar as well as a shade, and loops nothing', () => {
    expect(shellCss).toMatch(/\.shell-pill::before \{[^}]*width: 3px/)
    expect(shellCss).not.toMatch(/infinite/)
  })
})
