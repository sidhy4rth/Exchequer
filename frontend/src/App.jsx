import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { role } from './session'

// Each page is its own chunk. The sign-in globe (map data, d3-geo) and the
// trace graph (force layout) are the heavy parts and no page needs both, so a
// visitor downloads only what the page in front of them draws.
const Citizen = lazy(() => import('./routes/Citizen'))
const Home = lazy(() => import('./routes/Home'))
const SignIn = lazy(() => import('./routes/SignIn'))
const TraceView = lazy(() => import('./routes/TraceView'))
const Verify = lazy(() => import('./routes/Verify'))
const Batch = lazy(() => import('./routes/Batch'))

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
    <Suspense fallback={null}>
    <Routes>
      <Route path="/signin" element={<Navigate to="/signin/investigator" replace />} />
      <Route path="/signin/investigator" element={<SignIn as="investigator" />} />
      <Route path="/signin/citizen" element={<SignIn as="citizen" />} />
      <Route path="/citizen" element={<Gate as="citizen"><Citizen /></Gate>} />
      {/* Public: whoever receives a report checks it here, signed in or not. */}
      <Route path="/verify" element={<Verify />} />
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
      <Route path="/demo/:demoNo" element={<Gate as="investigator"><TraceView /></Gate>} />
      <Route path="/batch/:batchId" element={<Gate as="investigator"><Batch /></Gate>} />
      <Route path="*" element={<Gate as="investigator"><Home /></Gate>} />
    </Routes>
    </Suspense>
  )
}
