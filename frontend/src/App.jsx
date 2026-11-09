import { lazy, Suspense } from 'react'
import { Navigate, Outlet, Route, Routes, useLocation, useMatch } from 'react-router-dom'
import AppShell from './components/AppShell'
import DemoBanner from './components/DemoBanner'
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
const Work = lazy(() => import('./routes/Work'))

/** The demo front doors: each part of the app needs the tab to have chosen
 * the matching view once, and says on every page that it is a demo with no
 * accounts (the citizen's banner; the console's sidebar). Not security --
 * see session.js. */
function Gate({ as, children }) {
  const location = useLocation()
  const current = role()
  if (current === as) return as === 'citizen' ? <><DemoBanner as={as} />{children}</> : children
  if (current) return <Navigate to={current === 'citizen' ? '/citizen' : '/'} replace />
  return <Navigate to={`/signin/${as}`} replace state={{ from: location.pathname + location.search }} />
}

/** The investigator's console: every page inside the one shell, kept
 * mounted from page to page. Verify a report is public: whoever receives a
 * report checks it there, signed in or not, so anyone but an officer sees it
 * on its own. */
function Console() {
  const verify = useMatch('/verify')
  if (verify && role() !== 'investigator') return <Outlet />
  return <Gate as="investigator"><AppShell /></Gate>
}
const VerifyPage = () => <Verify embedded={role() === 'investigator'} />

export default function App() {
  return (
    <Suspense fallback={null}>
    <Routes>
      <Route path="/signin" element={<Navigate to="/signin/investigator" replace />} />
      <Route path="/signin/investigator" element={<SignIn as="investigator" />} />
      <Route path="/signin/citizen" element={<SignIn as="citizen" />} />
      <Route path="/citizen" element={<Gate as="citizen"><Citizen /></Gate>} />
      <Route element={<Console />}>
        <Route path="/verify" element={<VerifyPage />} />
        <Route path="/" element={<Home />} />
        <Route path="/trace/new" element={<Work page="new" />} />
        <Route path="/cases" element={<Work page="cases" />} />
        <Route path="/watchlist" element={<Work page="watchlist" />} />
        <Route path="/requests" element={<Work page="requests" />} />
        <Route path="/batch" element={<Work page="batch" />} />
        {/* The address is the subject of the investigation, so it belongs in the
            path; chain, asset and depth are parameters of how it is traced and
            ride in the query string. Opened from a link, the page shows what it
            would run and waits for a click (TraceView's ConfirmTrace); share a
            finished trace by its /case link instead. */}
        <Route path="/trace/:address" element={<TraceView />} />
        {/* A stored case is addressed by its own id. Opening one must never
            re-run the traversal: the point of the case store is that it holds
            what was found at the time, including pattern findings that live data
            may no longer satisfy. */}
        <Route path="/case/:caseId" element={<TraceView />} />
        <Route path="/demo/:demoNo" element={<TraceView />} />
        <Route path="/batch/:batchId" element={<Batch />} />
        <Route path="*" element={<Home />} />
      </Route>
    </Routes>
    </Suspense>
  )
}
