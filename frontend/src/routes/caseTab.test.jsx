import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { CASE_TABS, useCaseTab } from './caseTab'

// A case's tab lives in its URL (?tab=), so a link or a reload opens the
// same view; choosing one replaces the history entry instead of adding one.

function Probe() {
  const [tab, setTab] = useCaseTab()
  const { search, state } = useLocation()
  return (
    <div>
      <p data-testid="tab">{tab}</p>
      <p data-testid="search">{search}</p>
      <p data-testid="state">{JSON.stringify(state)}</p>
      <p data-testid="nav">{useNavigationType()}</p>
      {CASE_TABS.map((t) => <button key={t.key} onClick={() => setTab(t.key)}>{t.label}</button>)}
    </div>
  )
}

function at(entry) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes><Route path="*" element={<Probe />} /></Routes>
    </MemoryRouter>,
  )
}
const text = (id) => screen.getByTestId(id).textContent

describe('the case tab in the URL', () => {
  it('names the five views in order', () => {
    expect(CASE_TABS.map((t) => t.key)).toEqual(['flow', 'timeline', 'entities', 'evidence', 'letters'])
    expect(CASE_TABS.map((t) => t.label)).toEqual(['Flow', 'Timeline', 'Entities', 'Evidence', 'Letters'])
  })

  it('opens on Flow, and on the view ?tab= names', () => {
    at('/demo/11')
    expect(text('tab')).toBe('flow')
  })

  it.each(['timeline', 'entities', 'evidence', 'letters'])('reads ?tab=%s', (tab) => {
    at(`/demo/11?tab=${tab}`)
    expect(text('tab')).toBe(tab)
  })

  it.each(['nope', '', 'Evidence', 'flow,letters'])('reads an unknown ?tab=%s as Flow', (tab) => {
    at(`/demo/11?tab=${tab}`)
    expect(text('tab')).toBe('flow')
  })

  it('keeps chain, depth and pay, and the navigation state, replacing the entry', async () => {
    const user = userEvent.setup()
    at({ pathname: '/trace/TAbc', search: '?chain=tron&asset=USDT&depth=3&pay=0x1,0x2', state: { startedHere: true } })
    await user.click(screen.getByRole('button', { name: 'Letters' }))
    expect(text('tab')).toBe('letters')
    const params = new URLSearchParams(text('search'))
    expect(Object.fromEntries(params)).toEqual({ chain: 'tron', asset: 'USDT', depth: '3', pay: '0x1,0x2', tab: 'letters' })
    expect(text('nav')).toBe('REPLACE')
    expect(JSON.parse(text('state'))).toEqual({ startedHere: true })
    await user.click(screen.getByRole('button', { name: 'Flow' }))
    expect(text('tab')).toBe('flow')
    expect(Object.fromEntries(new URLSearchParams(text('search')))).toEqual({ chain: 'tron', asset: 'USDT', depth: '3', pay: '0x1,0x2' })
  })
})
