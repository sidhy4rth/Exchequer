import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
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
    expect(group('Monitor')).toEqual([['Watchlist', '/watchlist'], ['Requests', '/requests']])
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
    expect(menu.getAllByRole('link').map((a) => a.textContent)).toEqual(['Bulk intake', 'Requests', 'Verify a report'])
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
    expect(menu.getAllByRole('link').map((a) => a.textContent)).toEqual(['Bulk intake', 'Requests', 'Verify a report', 'Admin'])
    expect(menu.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
    expect(menu.queryByRole('button', { name: /switch to/i })).toBeNull()
  })
})
