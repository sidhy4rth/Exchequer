import { useNavigate } from 'react-router-dom'
import { forgetDemoCode } from '../demoCode'
import { enterAs, leave } from '../session'
import './DemoBanner.css'

const VIEWS = {
  investigator: { name: 'Investigator', home: '/' },
  citizen: { name: 'Citizen', home: '/citizen' },
}

/** The demo view's two ways out, for the banner here and the console's
 * sidebar: switch to the other view, or leave for the front door. */
export function useDemoView(as) {
  const navigate = useNavigate()
  const other = as === 'investigator' ? 'citizen' : 'investigator'
  return {
    name: VIEWS[as].name,
    other: VIEWS[other].name,
    switchView() {
      enterAs(other)
      navigate(VIEWS[other].home)
    },
    exit() {
      leave()
      forgetDemoCode()
      navigate(`/signin/${as}`)
    },
  }
}

/** Says what this is on every page behind the front door: a demo with no
 * accounts, seen as one of two views, either of which anyone may pick. The
 * investigator's console says it in its sidebar instead (AppShell). */
export default function DemoBanner({ as }) {
  const { name, other, switchView, exit } = useDemoView(as)
  return (
    <div className="demo-banner" role="note" aria-label="Preview">
      <span><strong>Preview</strong> · no accounts yet · viewing as {name}</span>
      <span className="demo-banner-actions">
        <button type="button" className="quiet" onClick={switchView}>Switch to {other.toLowerCase()} view</button>
        <button type="button" className="quiet" onClick={exit}>Leave</button>
      </span>
    </div>
  )
}
