import { useNavigate } from 'react-router-dom'
import { forgetDemoCode } from '../demoCode'
import { enterAs, leave } from '../session'
import './DemoBanner.css'

const VIEWS = {
  investigator: { name: 'Investigator', home: '/' },
  citizen: { name: 'Citizen', home: '/citizen' },
}

/** Says what this is on every page behind the front door: a demo with no
 * accounts, seen as one of two views, either of which anyone may pick. */
export default function DemoBanner({ as }) {
  const navigate = useNavigate()
  const other = as === 'investigator' ? 'citizen' : 'investigator'

  function switchView() {
    enterAs(other)
    navigate(VIEWS[other].home)
  }

  function exit() {
    leave()
    forgetDemoCode()
    navigate(`/signin/${as}`)
  }

  return (
    <div className="demo-banner" role="note" aria-label="Preview">
      <span><strong>Preview</strong> · no accounts yet · viewing as {VIEWS[as].name}</span>
      <span className="demo-banner-actions">
        <button type="button" className="quiet" onClick={switchView}>Switch to {VIEWS[other].name.toLowerCase()} view</button>
        <button type="button" className="quiet" onClick={exit}>Leave</button>
      </span>
    </div>
  )
}
