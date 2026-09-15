import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { fetchAuthStatus, logout as apiLogout } from './api'

// Who is signed in, if this instance requires it. The gate is a shared access
// code on the backend; the page only asks the backend and renders the answer.
// `required` false means an ungated instance: everything works, nobody is
// recorded, and the report says so.
const AuthContext = createContext({ required: false, officer: null, ready: false, refresh: () => {}, signOut: () => {} })

export function AuthProvider({ children }) {
  const [state, setState] = useState({ required: false, officer: null, ready: false })

  const refresh = useCallback(async () => {
    try {
      const s = await fetchAuthStatus()
      setState({ required: !!s.required, officer: s.officer ?? null, ready: true })
    } catch {
      // Backend unreachable: let the pages render and show their own error.
      setState({ required: false, officer: null, ready: true })
    }
  }, [])

  const signOut = useCallback(async () => {
    try { await apiLogout() } catch { /* the cookie may already be gone */ }
    setState((s) => ({ ...s, officer: null }))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  return <AuthContext.Provider value={{ ...state, refresh, signOut }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
