import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Home from './routes/Home'
import SignIn from './routes/SignIn'
import TraceView from './routes/TraceView'
import { signedIn } from './session'

/** The demo front door: anything but the sign-in page needs the tab to have
 * passed it once. Not security -- see session.js. */
function Gate({ children }) {
  const location = useLocation()
  if (!signedIn()) return <Navigate to="/signin" replace state={{ from: location.pathname + location.search }} />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/signin" element={<SignIn />} />
      <Route path="/" element={<Gate><Home /></Gate>} />
      {/* The address is the subject of the investigation, so it belongs in the
          path; chain, asset and depth are parameters of how it is traced and
          ride in the query string. That makes a trace a shareable URL. */}
      <Route path="/trace/:address" element={<Gate><TraceView /></Gate>} />
      {/* A stored case is addressed by its own id. Opening one must never
          re-run the traversal: the point of the case store is that it holds
          what was found at the time, including pattern findings that live data
          may no longer satisfy. */}
      <Route path="/case/:caseId" element={<Gate><TraceView /></Gate>} />
      <Route path="*" element={<Gate><Home /></Gate>} />
    </Routes>
  )
}
