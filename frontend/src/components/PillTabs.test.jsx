import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import PillTabs from './PillTabs'

const TABS = [
  { key: 'flow', label: 'Flow', content: <p>Flow panel</p> },
  { key: 'timeline', label: 'Timeline', content: <p>Timeline panel</p> },
  { key: 'entities', label: 'Entities', content: <p>Entities panel</p> },
]

describe('pill tabs', () => {
  it('is a named tablist whose tabs each control a panel', () => {
    render(<PillTabs label="Case views" tabs={TABS} />)
    const list = screen.getByRole('tablist', { name: 'Case views' })
    const tabs = screen.getAllByRole('tab')
    expect(list).toContainElement(tabs[0])
    expect(tabs.map((t) => t.getAttribute('aria-selected'))).toEqual(['true', 'false', 'false'])
    for (const tab of tabs) {
      const panel = document.getElementById(tab.getAttribute('aria-controls'))
      expect(panel).toHaveAttribute('role', 'tabpanel')
      expect(panel).toHaveAttribute('aria-labelledby', tab.id)
    }
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Flow panel')
    expect(screen.getByText('Timeline panel').closest('[role="tabpanel"]')).not.toBeVisible()
  })

  it('lets only the selected tab take Tab focus', () => {
    render(<PillTabs label="Case views" tabs={TABS} />)
    expect(screen.getAllByRole('tab').map((t) => t.tabIndex)).toEqual([0, -1, -1])
  })

  it('moves with the arrow keys, Home and End, wrapping at the ends', async () => {
    const user = userEvent.setup()
    render(<PillTabs label="Case views" tabs={TABS} />)
    const [flow, timeline, entities] = screen.getAllByRole('tab')
    await user.click(flow)
    await user.keyboard('{ArrowRight}')
    expect(timeline).toHaveFocus()
    expect(timeline).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Timeline panel')
    await user.keyboard('{End}')
    expect(entities).toHaveFocus()
    await user.keyboard('{ArrowRight}')
    expect(flow).toHaveFocus()
    await user.keyboard('{ArrowLeft}')
    expect(entities).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{Home}')
    expect(flow).toHaveAttribute('aria-selected', 'true')
    expect(screen.getAllByRole('tab').map((t) => t.tabIndex)).toEqual([0, -1, -1])
  })

  it('can be driven by the page that holds it', async () => {
    const user = userEvent.setup()
    const seen = vi.fn()
    function Page() {
      const [tab, setTab] = useState('entities')
      return <PillTabs label="Case views" tabs={TABS} value={tab} onChange={(k) => { seen(k); setTab(k) }} />
    }
    render(<Page />)
    expect(screen.getByRole('tab', { name: 'Entities' })).toHaveAttribute('aria-selected', 'true')
    await user.click(screen.getByRole('tab', { name: 'Flow' }))
    expect(seen).toHaveBeenCalledWith('flow')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Flow panel')
  })
})
