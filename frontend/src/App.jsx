import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Citizen from './routes/Citizen'
import Home from './routes/Home'
import SignIn from './routes/SignIn'
import TraceView from './routes/TraceView'
import { role } from './session'

/** The demo front doors: each part of the app needs the tab to have passed
 * the matching sign-in once. Not security -- see session.js. */
function Gate({ as, children }) {
  const location = useLocation()
  const current = role()
  if (current === as) return children
  if (current) return <Navigate to={current === 'citizen' ? '/citizen' : '/'} replace />
  return <Navigate to={`/signin/${as}`} replace state={{ from: location.pathname + location.search }} />
}

export default function App() {
  return (
    <Routes>
      <Route path="/signin" element={<Navigate to="/signin/investigator" replace />} />
      <Route path="/signin/investigator" element={<SignIn as="investigator" />} />
      <Route path="/signin/citizen" element={<SignIn as="citizen" />} />
      <Route path="/citizen" element={<Gate as="citizen"><Citizen /></Gate>} />
      <Route path="/" element={<Gate as="investigator"><Home /></Gate>} />
      {/* The address is the subject of the investigation, so it belongs in the
          path; chain, asset and depth are parameters of how it is traced and
          ride in the query string. That makes a trace a shareable URL. */}
      <Route path="/trace/:address" element={<Gate as="investigator"><TraceView /></Gate>} />
      {/* A stored case is addressed by its own id. Opening one must never
          re-run the traversal: the point of the case store is that it holds
          what was found at the time, including pattern findings that live data
          may no longer satisfy. */}
      <Route path="/case/:caseId" element={<Gate as="investigator"><TraceView /></Gate>} />
      <Route path="*" element={<Gate as="investigator"><Home /></Gate>} />
    </Routes>
  )
}
