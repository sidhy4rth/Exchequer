import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { changePassword, signIn, signOut } from '../api/accounts'
import ExchangeGlobe from '../components/ExchangeGlobe'
import Mark from '../components/Mark'
import { enterAs, signedInAs, signedOut, useAccount } from '../session'
import { plain } from '../text'
import './SignIn.css'

// Two front doors, investigator and citizen, each its own page and both the
// same scene: a globe of the world's exchanges, which turns when dragged and
// names an exchange on hover, and nothing else on screen. Clicking the Exchequer mark in the top
// bar (or the globe) opens the door -- the mark flies out of the logo into
// the globe's core, the globe collapses into it, flashes, and the sign-in
// card assembles itself from the chequer's sixteen squares. On the
// investigator's card an officer signs in (an officer with a temporary
// password chooses their own first); anyone else looks around as a demo,
// which only picks which view this tab shows (see session.js). Citizens have
// no accounts yet. The backend decides what an officer may do, not this page.

const DOORS = {
  investigator: {
    who: 'Investigator',
    title: 'Follow the money.',
    lede: 'Trace stolen crypto from a victim’s wallet to the exchange that can freeze it.',
    button: 'Look around as a demo',
    note: 'Officers sign in with the account their unit’s admin made. Anyone else can look around: the recorded cases, and live tracing where this site allows it.',
    home: '/',
  },
  citizen: {
    who: 'Citizen',
    title: 'Lost money to a crypto scam?',
    lede: 'A page for victims to report a scam and follow their case. It is still being built.',
    button: 'Open the citizen page',
    note: 'Citizens have no accounts yet, so there is nothing to sign in with: anyone can look around the citizen page.',
    home: '/citizen',
  },
}

// describedBy: the ids read with the box itself (a rule, an error); a form's
// own description is not read when focus lands on a box.
const Field = ({ label, invalid, describedBy, ...input }) => (
  <label className="field">
    <span className="micro">{label}</span>
    <input {...input} aria-invalid={invalid || undefined} aria-describedby={describedBy || undefined} required />
  </label>
)

/** E-mail and password. A refusal is shown in the backend's own words. */
function SignInForm() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  async function submit(event) {
    event.preventDefault()
    if (!email.trim() || !password) { setError('Enter your e-mail and password.'); return }
    setBusy(true)
    setError(null)
    try {
      signedInAs(await signIn(email.trim(), password))
    } catch (failed) {
      setError(failed.message)
      setPassword('')
      setBusy(false)
    }
  }
  return (
    <form className="door-form" onSubmit={submit} noValidate>
      <Field label="E-mail" type="email" autoComplete="username" value={email} autoFocus spellCheck={false}
        onChange={(e) => setEmail(e.target.value)} invalid={Boolean(error)} describedBy={error && 'signin-error'} />
      <Field label="Password" type="password" autoComplete="current-password" value={password}
        onChange={(e) => setPassword(e.target.value)} invalid={Boolean(error)} describedBy={error && 'signin-error'} />
      {error && <p id="signin-error" className="signin-error" role="alert">{error}</p>}
      <button type="submit" className="primary enter" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
  )
}

/** A temporary password (a new or reset account) is changed before anything else. */
function ChangePassword({ officer }) {
  const [fields, setFields] = useState({ current: '', next: '', again: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const bind = (key) => ({ value: fields[key], onChange: (e) => setFields({ ...fields, [key]: e.target.value }) })
  async function submit(event) {
    event.preventDefault()
    const { current, next, again } = fields
    const wrong = !current || !next ? 'Fill in all three fields.'
      : next.length < 12 ? 'Use at least 12 characters.'
      : next !== again ? 'The two new passwords differ.'
      : next === current ? 'Choose a password different from the temporary one.' : null
    if (wrong) { setError(wrong); return }
    setBusy(true)
    setError(null)
    try {
      signedInAs(await changePassword(current, next))
    } catch (failed) {
      setError(failed.message)
      setBusy(false)
    }
  }
  // As the sidebar's Sign out: while the cookie may still be good, the
  // officer is not told they are out.
  async function leave() {
    try {
      await signOut()
      signedOut()
    } catch (failed) {
      setError(`Could not sign out: ${failed.message}`)
    }
  }
  const told = error ? 'signin-error' : undefined
  return (
    <>
      <div className="portal-head">
        <Mark size={30} />
        <h1>Choose your own password</h1>
        <p>{plain(officer.name)}, your account has a temporary password. Choose one only you know before you go on.</p>
      </div>
      <form className="door-form" onSubmit={submit} noValidate>
        <Field label="Temporary password" type="password" autoComplete="current-password" autoFocus {...bind('current')} invalid={Boolean(error)} describedBy={told} />
        <Field label="New password" type="password" autoComplete="new-password" {...bind('next')} invalid={Boolean(error)}
          describedBy={['password-rule', told].filter(Boolean).join(' ')} />
        <Field label="New password, again" type="password" autoComplete="new-password" {...bind('again')} invalid={Boolean(error)} describedBy={told} />
        <p id="password-rule" className="demo-mode">At least 12 characters. A few unrelated words are easy to remember and hard to guess.</p>
        {error && <p id="signin-error" className="signin-error" role="alert">{error}</p>}
        <button type="submit" className="primary enter" disabled={busy}>{busy ? 'Saving…' : 'Save and continue'}</button>
        <button type="button" className="quiet door-out" onClick={leave}>Sign out instead</button>
      </form>
    </>
  )
}

const TILES = Array.from({ length: 16 }, (_, n) => ({ i: Math.floor(n / 4), j: n % 4 }))

export default function SignIn({ as }) {
  const navigate = useNavigate()
  const location = useLocation()
  const door = DOORS[as]
  const { officer } = useAccount()
  const changing = as === 'investigator' && officer?.must_change_password
  // shut -> open -> closing -> shut; a password to change opens it at once.
  const [phase, setPhase] = useState(changing ? 'open' : 'shut')
  // Sealed: the card's body has taken the tiles' colour, so the tiles go.
  const [sealed, setSealed] = useState(false)
  useEffect(() => { if (phase === 'shut') setSealed(false) }, [phase])
  const slotRef = useRef(null)

  const openDoor = useCallback(() => setPhase('open'), [])

  // The console is the next page. Fetch its code while the globe spins so
  // signing in never waits on a download.
  useEffect(() => { import('./Home') }, [])

  useEffect(() => { if (changing) setPhase('open') }, [changing])

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

  function enterDemo(event) {
    event.preventDefault()
    enterAs(as)
    navigate(location.state?.from ?? door.home, { replace: true })
  }

  // Signed in, with a password of their own: on to the console.
  if (as === 'investigator' && officer && !changing) return <Navigate to={location.state?.from ?? door.home} replace />

  return (
    // main: the landmark a screen reader skips to past the header (WCAG 2.4.1).
    <main className={`gate gate-${as} gate-${phase}`}>
      <ExchangeGlobe
        open={phase === 'open'}
        onOpen={openDoor}
        anchorRef={slotRef}
        role={as}
        hint={(
          <button type="button" className="gate-hint" onClick={openDoor}>
            <span className="micro">{door.who} access</span>
            <span>Click anywhere to enter</span>
          </button>
        )}
      />

      <header className="gate-top">
        {/* The mark itself is drawn in 3D by the globe's canvas into this
            slot, so it can fly out of the logo when the door opens. */}
        <button type="button" className="brand brand-door" onClick={openDoor} aria-label={`Exchequer: enter as ${door.who.toLowerCase()}`}>
          <span className="brand-slot" ref={slotRef} aria-hidden="true" />
          <span>Exchequer</span>
        </button>
        <nav className="gate-doors" aria-label="Who is signing in">
          <Link to="/signin/investigator" replace className={as === 'investigator' ? 'on' : ''}>Investigator</Link>
          <Link to="/signin/citizen" replace className={as === 'citizen' ? 'on' : ''}>Citizen</Link>
        </nav>
      </header>

      {phase !== 'shut' && (
        <div className="portal" role="dialog" aria-modal="true" aria-label={`Enter as ${door.who.toLowerCase()}`}>
          <div className="portal-scrim" onClick={() => setPhase('closing')} />
          <div className="portal-card">
            {!sealed && <div className="portal-tiles" aria-hidden="true">
              {TILES.map(({ i, j }) => (
                <span
                  key={`${i}${j}`}
                  className={i === 2 && j === 2 ? 'red' : ''}
                  style={{ '--i': i, '--j': j, '--d': Math.hypot(i - 2, j - 2) }}
                />
              ))}
            </div>}
            <div className="portal-body" onAnimationEnd={(e) => { if (e.target === e.currentTarget && e.animationName === 'portal-solid') setSealed(true) }}>
              <button type="button" className="portal-close" onClick={() => setPhase('closing')} aria-label="Close">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M2 2l8 8M10 2l-8 8" /></svg>
              </button>
              <nav className="portal-switch" aria-label="Who is signing in">
                <Link to="/signin/investigator" replace className={as === 'investigator' ? 'on' : ''}>Investigator</Link>
                <Link to="/signin/citizen" replace className={as === 'citizen' ? 'on' : ''}>Citizen</Link>
              </nav>
              {changing ? <ChangePassword officer={officer} /> : (
                <>
                  <div className="portal-head" key={as}>
                    <Mark size={30} />
                    <h1>{door.title}</h1>
                    <p>{door.lede}</p>
                  </div>
                  {as === 'investigator' && <SignInForm />}
                  <form className={`door-form door-demo-${as}`} onSubmit={enterDemo} key={`form-${as}`}>
                    <p className="demo-mode">
                      <span className="micro">{as === 'investigator' ? 'No account?' : 'Preview'}</span>
                      {door.note}
                    </p>
                    <button type="submit" className={as === 'investigator' ? 'enter' : 'primary enter'} autoFocus={as !== 'investigator'}>
                      {door.button}
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M2 7h10M8 3l4 4-4 4" /></svg>
                    </button>
                  </form>
                </>
              )}
            </div>
          </div>
        </div>
      )}

    </main>
  )
}
