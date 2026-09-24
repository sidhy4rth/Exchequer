import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import ExchangeGlobe from '../components/ExchangeGlobe'
import Mark from '../components/Mark'
import { demoAccount, signIn } from '../session'

// Two front doors, investigator and citizen, each its own page and both the
// same scene: a globe of the world's exchanges, which turns when dragged and
// names an exchange on hover, and nothing else on screen. Clicking the Exchequer mark in the top
// bar (or the globe) opens the door -- the mark flies out of the logo into
// the globe's core, the globe collapses into it, flashes, and the sign-in
// card assembles itself from the chequer's sixteen squares. The forms are
// demonstration doors (see session.js), not access control.

const DOORS = {
  investigator: {
    who: 'Investigator',
    title: 'Follow the money.',
    lede: 'Trace stolen crypto from a victim’s wallet to the exchange that can freeze it.',
    user: 'Officer ID',
    userHint: 'name or service ID',
    pass: 'Access code',
    button: 'Open the console',
    home: '/',
  },
  citizen: {
    who: 'Citizen',
    title: 'Lost money to a crypto scam?',
    lede: 'Sign in to your Exchequer account.',
    user: 'Email or mobile number',
    userHint: 'you@example.com',
    pass: 'Password',
    button: 'Sign in',
    home: '/citizen',
  },
}

const TILES = Array.from({ length: 16 }, (_, n) => ({ i: Math.floor(n / 4), j: n % 4 }))

export default function SignIn({ as }) {
  const navigate = useNavigate()
  const location = useLocation()
  const door = DOORS[as]
  // shut -> open -> closing -> shut
  const [phase, setPhase] = useState('shut')
  // Prefilled with the demo account for this door, so a judge can go
  // straight in; switching doors swaps in the other account.
  const [user, setUser] = useState(demoAccount(as).user)
  const [pass, setPass] = useState(demoAccount(as).pass)
  const [filledFor, setFilledFor] = useState(as)
  if (filledFor !== as) {
    setFilledFor(as)
    setUser(demoAccount(as).user)
    setPass(demoAccount(as).pass)
  }
  const [error, setError] = useState(0)
  const slotRef = useRef(null)

  const openDoor = useCallback(() => setPhase('open'), [])

  useEffect(() => {
    if (phase !== 'closing') return undefined
    const id = setTimeout(() => setPhase('shut'), 380)
    return () => clearTimeout(id)
  }, [phase])

  useEffect(() => {
    function key(event) {
      if (event.key === 'Escape' && phase === 'open') setPhase('closing')
      if (event.key === 'Enter' && phase === 'shut' && document.activeElement === document.body) setPhase('open')
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [phase])

  function submit(event) {
    event.preventDefault()
    if (signIn(as, user, pass)) {
      navigate(location.state?.from ?? door.home, { replace: true })
    } else {
      setError((n) => n + 1)
    }
  }

  return (
    <div className={`gate gate-${as} gate-${phase}`}>
      <ExchangeGlobe
        open={phase === 'open'}
        onOpen={openDoor}
        anchorRef={slotRef}
        role={as}
        hint={(
          <button type="button" className="gate-hint" onClick={openDoor}>
            <span className="micro">{door.who} access</span>
            <span>Click the Exchequer mark to sign in</span>
          </button>
        )}
      />

      <header className="gate-top">
        {/* The mark itself is drawn in 3D by the globe's canvas into this
            slot, so it can fly out of the logo when the door opens. */}
        <button type="button" className="brand brand-door" onClick={openDoor} aria-label={`Exchequer: open ${door.who.toLowerCase()} sign-in`}>
          <span className="brand-slot" ref={slotRef} aria-hidden="true" />
          <span>Exchequer</span>
        </button>
        <nav className="gate-doors" aria-label="Who is signing in">
          <Link to="/signin/investigator" replace className={as === 'investigator' ? 'on' : ''}>Investigator</Link>
          <Link to="/signin/citizen" replace className={as === 'citizen' ? 'on' : ''}>Citizen</Link>
        </nav>
      </header>

      {phase !== 'shut' && (
        <div className="portal" role="dialog" aria-modal="true" aria-label={`${door.who} sign-in`}>
          <div className="portal-scrim" onClick={() => setPhase('closing')} />
          <div className="portal-card" data-shake={error === 0 ? undefined : error % 2}>
            <div className="portal-tiles" aria-hidden="true">
              {TILES.map(({ i, j }) => (
                <span
                  key={`${i}${j}`}
                  className={i === 2 && j === 2 ? 'red' : ''}
                  style={{ '--i': i, '--j': j, '--d': Math.hypot(i - 2, j - 2) }}
                />
              ))}
            </div>
            <div className="portal-body">
              <button type="button" className="portal-close" onClick={() => setPhase('closing')} aria-label="Close">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M2 2l8 8M10 2l-8 8" /></svg>
              </button>
              <nav className="portal-switch" aria-label="Who is signing in">
                <Link to="/signin/investigator" replace className={as === 'investigator' ? 'on' : ''}>Investigator</Link>
                <Link to="/signin/citizen" replace className={as === 'citizen' ? 'on' : ''}>Citizen</Link>
              </nav>
              <div className="portal-head" key={as}>
                <Mark size={30} />
                <h1>{door.title}</h1>
                <p>{door.lede}</p>
              </div>
              <form className="door-form" onSubmit={submit} autoComplete="off" key={`form-${as}`}>
                <label className="field">
                  <span className="micro">{door.user}</span>
                  <input value={user} onChange={(e) => { setUser(e.target.value); setError(0) }} placeholder={door.userHint} spellCheck={false} />
                </label>
                <label className="field">
                  <span className="micro">{door.pass}</span>
                  <input type="password" value={pass} onChange={(e) => { setPass(e.target.value); setError(0) }} placeholder="••••••••" aria-invalid={error > 0} />
                </label>
                {error > 0 && <span className="signin-error">Not recognised.</span>}
                <button type="submit" className="primary enter" disabled={!user || !pass} autoFocus>
                  {door.button}
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M2 7h10M8 3l4 4-4 4" /></svg>
                </button>
              </form>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
