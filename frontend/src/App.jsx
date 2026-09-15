import { Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import Home from './routes/Home'
import SignIn from './routes/SignIn'
import TraceView from './routes/TraceView'

function Gate({ children }) {
  const { required, officer, ready } = useAuth()
  if (!ready) return null
  // With sign-in on and nobody signed in, every page is the sign-in page.
  if (required && !officer) return <SignIn />
  return children
}

export default function App() {
  return (
    <AuthProvider>
      <Gate>
        <Routes>
      <Route path="/" element={<Home />} />
      {/* The address is the subject of the investigation, so it belongs in the
          path; chain, asset and depth are parameters of how it is traced and
          ride in the query string. That makes a trace a shareable URL. */}
      <Route path="/trace/:address" element={<TraceView />} />
      {/* A stored case is addressed by its own id. Opening one must never
          re-run the traversal: the point of the case store is that it holds
          what was found at the time, including pattern findings that live data
          may no longer satisfy. */}
      <Route path="/case/:caseId" element={<TraceView />} />
      <Route path="*" element={<Home />} />
        </Routes>
      </Gate>
    </AuthProvider>
  )
}
