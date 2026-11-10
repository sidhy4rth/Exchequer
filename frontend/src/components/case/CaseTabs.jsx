import { useRef } from 'react'
import PillTabs from '../PillTabs'
import { CASE_TABS } from '../../routes/caseTab'

const ICON = {
  flow: 'M1.5 4c5 0 6 8 13 8M1.5 8h13M1.5 12c5 0 6-8 13-8',
  timeline: 'M1.5 8h13M4 5v6M8 3v10M12 6v4',
  entities: 'M5 5a3 3 0 1 0 0.01 0M11.5 9.5a2.5 2.5 0 1 0 0.01 0M7.5 7l2.5 2',
  evidence: 'M8 1.8l5 2v4.1c0 3-2.2 5.2-5 6.3-2.8-1.1-5-3.3-5-6.3V3.8z',
  letters: 'M2.5 2.5h8l3 3v8h-11zM5 8h6M5 10.5h6',
}

/** The case's five views as pill tabs (arrow keys, Home and End). A view is
 * drawn the first time it is chosen and then kept, hidden, while another
 * shows: a graph keeps its zoom and a list what it had revealed. `panels`
 * maps each tab's key to what it holds. */
export default function CaseTabs({ value, onChange, panels }) {
  const seen = useRef(new Set())
  seen.current.add(value)
  const tabs = CASE_TABS.map((t) => ({
    ...t,
    icon: <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><path d={ICON[t.key]} /></svg>,
    content: seen.current.has(t.key) ? panels[t.key] : null,
  }))
  return <div className="case-tabs"><PillTabs label="Case views" tabs={tabs} value={value} onChange={onChange} /></div>
}
