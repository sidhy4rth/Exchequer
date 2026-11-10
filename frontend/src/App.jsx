import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Outlet, Route, Routes, useLocation, useMatch } from 'react-router-dom'
import AppShell from './components/AppShell'
import DemoBanner from './components/DemoBanner'
import { checkAccount, role, useAccount, watchAccount } from './session'

// Each page is its own chunk. The sign-in globe (map data, d3-geo) and the
// trace graph (force layout) are the heavy parts and no page needs both, so a
// visitor downloads only what the page in front of them draws.
const Citizen = lazy(() => import('./routes/Citizen'))
const Home = lazy(() => import('./routes/Home'))
const SignIn = lazy(() => import('./routes/SignIn'))
const TraceView = lazy(() => import('./routes/TraceView'))
const Verify = lazy(() => import('./routes/Verify'))
const Batch = lazy(() => import('./routes/Batch'))
const Cases = lazy(() => import('./routes/Cases'))
const Complaints = lazy(() => import('./routes/Complaints'))
const Work = lazy(() => import('./routes/Work'))
const Admin = lazy(() => import('./routes/Admin'))

/** An officer signed in, with a password of their own, is in the console. */
function useOfficerIn() {
  const { officer } = useAccount()
  return Boolean(officer && !officer.must_change_password)
}

/** The front doors: the console needs a signed-in officer or the tab to
 * have chosen the investigator's demo view once; the citizen's page needs
 * the citizen's view. A demo says so on every page (the citizen's banner;
 * the console's sidebar). An officer with a temporary password goes back to
 * the door to change it. Not security: the backend checks every call. */
function Gate({ as, children }) {
  const location = useLocation()
  const { status, officer } = useAccount()
  const current = role()
  const from = location.pathname + location.search
  if (as === 'investigator' && officer) {
    return officer.must_change_password ? <Navigate to="/signin/investigator" replace state={{ from }} /> : children
  }
  if (current === as) return as === 'citizen' ? <><DemoBanner as={as} />{children}</> : children
  if (status === 'unknown' || status === 'checking') return null // not yet known whether an officer is signed in
  if (current) return <Navigate to={current === 'citizen' ? '/citizen' : '/'} replace />
  return <Navigate to={`/signin/${as}`} replace state={{ from }} />
}

/** The investigator's console: every page inside the one shell, kept
 * mounted from page to page. Verify a report is public: whoever receives a
 * report checks it there, signed in or not, so anyone but an officer sees it
 * on its own. */
function Console() {
  const verify = useMatch('/verify')
  const inside = useOfficerIn() || role() === 'investigator'
  if (verify && !inside) return <Outlet />
  return <Gate as="investigator"><AppShell /></Gate>
}
function VerifyPage() {
  const inside = useOfficerIn() || role() === 'investigator'
  return <Verify embedded={inside} />
}

export default function App() {
  useEffect(() => { checkAccount(); return watchAccount() }, [])
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
        <Route path="/cases" element={<Cases />} />
        <Route path="/watchlist" element={<Work page="watchlist" />} />
        <Route path="/requests" element={<Work page="requests" />} />
        <Route path="/complaints" element={<Complaints />} />
        <Route path="/complaints/:reference" element={<Complaints />} />
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
        <Route path="/admin" element={<Admin />} />
        <Route path="*" element={<Home />} />
      </Route>
    </Routes>
    </Suspense>
  )
}
