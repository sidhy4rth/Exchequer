import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import CaseTabs from './CaseTabs'
import { CASE_TABS, useCaseTab } from '../../routes/caseTab'

// The case's five views: an ARIA tablist driven by ?tab=. A view is drawn
// the first time it is chosen and then kept, hidden, while another shows.

function Counted({ name, mounts }) {
  useEffect(() => { mounts.push(name) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return <p>{name} panel</p>
}

function Page({ mounts }) {
  const [tab, setTab] = useCaseTab()
  const panels = Object.fromEntries(CASE_TABS.map((t) => [t.key, <Counted key={t.key} name={t.key} mounts={mounts} />]))
  return <><CaseTabs value={tab} onChange={setTab} panels={panels} /><Where /></>
}

function Where() {
  return <p data-testid="search">{useLocation().search}</p>
}

function at(path, mounts = []) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="*" element={<Page mounts={mounts} />} /></Routes>
    </MemoryRouter>,
  )
  return mounts
}

describe('the case tabs', () => {
  it('is a tablist named Case views, with the tab the URL names chosen', () => {
    at('/demo/11?tab=evidence')
    const list = screen.getByRole('tablist', { name: 'Case views' })
    const tabs = screen.getAllByRole('tab')
    expect(list).toContainElement(tabs[0])
    expect(tabs.map((t) => t.textContent)).toEqual(['Flow', 'Timeline', 'Entities', 'Evidence', 'Letters'])
    expect(screen.getByRole('tab', { name: 'Evidence' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel', { name: 'Evidence' })).toHaveTextContent('evidence panel')
    expect(tabs.map((t) => t.tabIndex)).toEqual([-1, -1, -1, 0, -1])
  })

  it('moves and chooses with the arrow keys, Home and End, and the URL follows', async () => {
    const user = userEvent.setup()
    at('/demo/11')
    const tab = (name) => screen.getByRole('tab', { name })
    await user.click(tab('Flow'))
    await user.keyboard('{ArrowRight}')
    expect(tab('Timeline')).toHaveFocus()
    expect(tab('Timeline')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('search')).toHaveTextContent('?tab=timeline')
    await user.keyboard('{End}')
    expect(tab('Letters')).toHaveFocus()
    expect(screen.getByTestId('search')).toHaveTextContent('?tab=letters')
    await user.keyboard('{ArrowRight}')
    expect(tab('Flow')).toHaveFocus()
    expect(screen.getByTestId('search')).toBeEmptyDOMElement()
    await user.keyboard('{ArrowLeft}{Home}')
    expect(tab('Flow')).toHaveAttribute('aria-selected', 'true')
  })

  it('draws a view on its first visit and keeps it, hidden, after', async () => {
    const user = userEvent.setup()
    const mounts = at('/demo/11')
    expect(mounts).toEqual(['flow'])
    expect(screen.queryByText('timeline panel')).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Timeline' }))
    expect(mounts).toEqual(['flow', 'timeline'])
    expect(screen.getByText('flow panel')).not.toBeVisible()
    expect(screen.getByText('timeline panel')).toBeVisible()
    await user.click(screen.getByRole('tab', { name: 'Flow' }))
    await user.click(screen.getByRole('tab', { name: 'Timeline' }))
    expect(mounts).toEqual(['flow', 'timeline'])
    expect(screen.queryByText('letters panel')).not.toBeInTheDocument()
  })
})
