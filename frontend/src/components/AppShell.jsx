import { createContext, Suspense, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { fetchChains } from '../api'
import { signOut } from '../api/accounts'
import { forgetDemoCode } from '../demoCode'
import { useMedia } from '../phone'
import { findTarget } from '../find'
import { isAdmin, leave, signedOut, useAccount } from '../session'
import { plain } from '../text'
import { useDemoView } from './DemoBanner'
import Mark from './Mark'
import ThemeToggle from './ThemeToggle'
import './AppShell.css'

// The investigator's console around every page behind its front door: a
// sidebar of grouped pages, a header with breadcrumbs and a search box, and
// below 720 px a tab bar at the foot of the screen instead of the sidebar.
//
// Motion: when the shell first opens the sidebar slides in from the left, a
// sheen passes down it once and its pages slide in one after another. A
// pill sits behind the page you are on and glides to the next one when you
// move. Nothing loops; with reduced motion asked for, all of it is still.

const STILL = '(prefers-reduced-motion: reduce)'
// The opening runs about 2.3 s; its classes come off after this, so nothing
// added later (the Admin group, say) replays it.
const INTRO_MS = 2600
const STAGGER_STEPS = 8

const ICON = {
  console: 'M2 2h5v5H2zM9 2h5v5H9zM2 9h5v5H2zM9 9h5v5H9z',
  trace: 'M8 2.5v11M2.5 8h11',
  cases: 'M2.5 3.5h11v9h-11zM2.5 6.5h11',
  bulk: 'M2.5 4h11M2.5 8h11M2.5 12h7',
  watch: 'M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8zM8 6a2 2 0 1 0 0 4a2 2 0 1 0 0-4',
  requests: 'M2.5 2.5h8l3 3v8h-11zM5 8h6M5 10.5h6',
  complaints: 'M2.5 9.5h3l1 1.5h3l1-1.5h3M2.5 9.5l1.5-6h8l1.5 6v4h-11z',
  verify: 'M8 1.8l5 2v4.1c0 3-2.2 5.2-5 6.3-2.8-1.1-5-3.3-5-6.3V3.8zM5.6 8.1l1.7 1.7 3.2-3.3',
  more: 'M3.5 8h.01M8 8h.01M12.5 8h.01',
  people: 'M8 7a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM3 14c.4-2.8 2.4-4.5 5-4.5s4.6 1.7 5 4.5',
}
const Icon = ({ name }) => (
  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={name === 'more' ? 2.4 : 1.4} strokeLinecap="round" strokeLinejoin="round"><path d={ICON[name]} /></svg>
)

// Each page, and the paths that sit inside it (a case inside Cases).
export const GROUPS = [
  ['Investigate', [
    { to: '/', label: 'Console', icon: 'console', inside: [] },
    { to: '/trace/new', label: 'New trace', icon: 'trace', inside: ['/trace/'] },
    { to: '/cases', label: 'Cases', icon: 'cases', inside: ['/case/', '/demo/'] },
    { to: '/batch', label: 'Bulk intake', icon: 'bulk', inside: ['/batch/'] },
  ]],
  ['Monitor', [
    { to: '/watchlist', label: 'Watchlist', icon: 'watch', inside: [] },
    { to: '/requests', label: 'Requests', icon: 'requests', inside: [] },
    { to: '/complaints', label: 'Complaints', icon: 'complaints', inside: ['/complaints/'] },
  ]],
  ['Evidence', [
    { to: '/verify', label: 'Verify a report', icon: 'verify', inside: [] },
  ]],
]
// Shown to an admin only; the backend refuses everyone else.
export const ADMIN_GROUP = ['Admin', [{ to: '/admin', label: 'Admin', icon: 'people', inside: [] }]]
const ITEMS = [...GROUPS, ADMIN_GROUP].flatMap(([, items]) => items)
// The phone's tab bar: the four most used, and More for the rest.
const ON_BAR = ['/', '/trace/new', '/cases', '/watchlist']

/** 'page' on the page itself, 'true' anywhere inside it. */
const where = (item, path) => (path === item.to ? 'page' : item.inside.some((p) => path.startsWith(p)) ? 'true' : undefined)
const middle = (a) => (a.length > 22 ? `${a.slice(0, 10)}…${a.slice(-8)}` : a)
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

/** The breadcrumbs for a path: its page, then what is open inside it. */
function trail(path) {
  const item = ITEMS.find((i) => where(i, path))
  if (!item) return []
  if (path === item.to) return [{ label: item.label }]
  const [, kind, raw = ''] = path.split('/')
  let id = raw
  try { id = decodeURIComponent(raw) } catch { /* shown as typed */ }
  const label = kind === 'demo' ? `Verified example ${id.padStart(2, '0')}` : kind === 'batch' ? 'Batch' : middle(plain(id))
  return [{ label: item.label, to: item.to }, { label, mono: kind === 'trace' || kind === 'case' }]
}

// A page inside the shell can name what it shows in the last breadcrumb once
// it knows (a case: its address), in place of what the path says.
const Crumb = createContext(() => {})
export function useCrumb(label) {
  const name = useContext(Crumb)
  useEffect(() => {
    name(label || null)
    return () => name(null)
  }, [name, label])
}

/** What the sidebar can say for certain about the chains: how many can
 * trace now (GET /chains `ready`), and how many flagged addresses those
 * chains hold to screen against (each hop meets only its own chain's list). */
function Status({ health }) {
  const chains = Object.values(health?.chains ?? {})
  const live = chains.filter((c) => c.ready)
  const ready = live.length
  const flagged = live.reduce((s, c) => s + Object.values(c.risk_labels ?? {}).reduce((a, b) => a + (b || 0), 0), 0)
  const down = health?.status === 'down'
  const line = !health ? 'Connecting…' : down ? 'Backend unreachable'
    : ready === chains.length && ready > 1 ? `All ${ready} chains ready to trace`
    : `${ready} of ${chains.length} ${chains.length === 1 ? 'chain' : 'chains'} ready to trace`
  return (
    <div className="shell-status">
      <span><i className={`shell-dot${down ? ' down' : health ? ' live' : ''}`} aria-hidden="true" />{line}</span>
      {!down && flagged > 0 && <small>{compact.format(flagged)} flagged addresses on file for screening</small>}
    </div>
  )
}

/** Wallet, transaction hash or case id → its page; anything else is said
 * to be not recognised, in place. */
function Find({ health, path }) {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [missed, setMissed] = useState(false)
  // The note sits over the top of the page, so it goes with the page, on
  // Escape, and once focus leaves the box.
  useEffect(() => setMissed(false), [path])
  function submit(event) {
    event.preventDefault()
    if (!text.trim()) return
    const to = findTarget(text, health)
    if (!to) { setMissed(true); return }
    setText('')
    navigate(to)
  }
  return (
    <div className="shell-find">
      <form role="search" aria-label="Find" onSubmit={submit}>
        <svg aria-hidden="true" width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><circle cx="7" cy="7" r="5" /><path d="M11 11l3.5 3.5" /></svg>
        <label htmlFor="shell-find" className="visually-hidden">Wallet, transaction hash or case ID</label>
        <input id="shell-find" type="search" placeholder="Wallet, hash or case" value={text} spellCheck={false} autoComplete="off"
          onChange={(e) => { setText(e.target.value); setMissed(false) }}
          onKeyDown={(e) => { if (e.key === 'Escape') setMissed(false) }} onBlur={() => setMissed(false)}
          aria-invalid={missed || undefined} aria-describedby={missed ? 'shell-find-missed' : undefined} />
      </form>
      {missed && <p id="shell-find-missed" className="shell-find-missed" role="alert">Not recognised: paste a wallet address, a transaction hash or a case ID.</p>}
    </div>
  )
}

/** Who is at the console, and the way out: the officer signed in, or the
 * demo's two ways out. */
function useWayOut(view) {
  const navigate = useNavigate()
  const { officer } = useAccount()
  const [error, setError] = useState(null)
  async function signOutNow() {
    try { await signOut() } catch (failed) { setError(`Could not sign out: ${failed.message}`); return }
    signedOut()
    leave()
    forgetDemoCode()
    navigate('/signin/investigator')
  }
  return { officer, admin: isAdmin(officer), error, signOutNow, view }
}

function WayOut({ out }) {
  if (!out.officer) {
    return (
      <>
        <button type="button" className="quiet" onClick={out.view.switchView}>Switch to {out.view.other.toLowerCase()} view</button>
        <button type="button" className="quiet" onClick={out.view.exit}>Leave</button>
      </>
    )
  }
  return (
    <>
      <button type="button" className="quiet" onClick={out.signOutNow}>Sign out</button>
      {out.error && <p className="shell-out-error" role="alert">{out.error}</p>}
    </>
  )
}

/** The phone's tab bar. More opens the other pages and the way out just
 * above it, next after More in the Tab order. A choice, Escape,
 * focus moving on or a press outside closes it, so the open menu never sits
 * over the control that has focus. */
function PhoneBar({ path, out }) {
  const [open, setOpen] = useState(false)
  const bar = useRef(null)
  const button = useRef(null)
  useEffect(() => setOpen(false), [path])
  useEffect(() => {
    if (!open) return undefined
    const outside = (event) => { if (!bar.current?.contains(event.target)) setOpen(false) }
    const onKey = (event) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      if (bar.current?.contains(document.activeElement)) button.current?.focus()
    }
    document.addEventListener('focusin', outside)
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('focusin', outside)
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  const rest = ITEMS.filter((i) => !ON_BAR.includes(i.to) && (out.admin || i !== ADMIN_GROUP[1][0]))
  return (
    <nav ref={bar} className="shell-tabs" aria-label="Sections">
      <ul>
        {ON_BAR.map((to) => ITEMS.find((i) => i.to === to)).map((item) => (
          <li key={item.to}><Link className="shell-tab" to={item.to} aria-current={where(item, path)}><Icon name={item.icon} />{item.label}</Link></li>
        ))}
        <li>
          <button ref={button} type="button" className={`shell-tab${rest.some((i) => where(i, path)) ? ' on' : ''}`}
            aria-expanded={open} aria-controls="shell-more" onClick={() => setOpen((o) => !o)}>
            <Icon name="more" />More
          </button>
          {open && (
            <div id="shell-more" className="shell-more">
              {rest.map((item) => (
                <Link key={item.to} to={item.to} aria-current={where(item, path)}><Icon name={item.icon} />{item.label}</Link>
              ))}
              <WayOut out={out} />
            </div>
          )}
        </li>
      </ul>
    </nav>
  )
}

/** Where the sidebar's pill sits: over the link marked aria-current inside
 * `nav`, measured again whenever `place` changes (the route, the Admin
 * group) or the sidebar resizes. Null while there is nothing to sit behind
 * (no current page here, or the sidebar hidden on a phone): the current
 * link then keeps its own background. Placed once, it glides from then on. */
function useNavPill(nav, place) {
  const [pill, setPill] = useState(null)
  useLayoutEffect(() => {
    const measure = () => {
      const on = nav.current?.querySelector('.shell-link[aria-current]')
      const next = on && on.offsetHeight > 0 ? { top: on.offsetTop, height: on.offsetHeight, to: on.getAttribute('href') } : null
      setPill((was) => {
        if (!next) return null
        if (was && was.top === next.top && was.height === next.height && was.to === next.to) return was
        return { ...next, glide: Boolean(was) }
      })
    }
    measure()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }
    const watch = new ResizeObserver(measure)
    if (nav.current) watch.observe(nav.current)
    return () => watch.disconnect()
  }, [nav, place])
  return pill
}

/** True for the shell's opening moments, unless reduced motion is asked
 * for (then never); the opening's classes come off once it has played. */
function useIntro(still) {
  const [intro, setIntro] = useState(!still)
  useEffect(() => {
    if (!intro) return undefined
    if (still) { setIntro(false); return undefined }
    const timer = setTimeout(() => setIntro(false), INTRO_MS)
    return () => clearTimeout(timer)
  }, [intro, still])
  return intro && !still
}

/** GET /chains for the shell's whole life. A miss (a restart, a 502 from
 * the proxy) says the backend is unreachable, then asks again after 2, 4, 8…
 * seconds (at most a minute apart), and at once when another page opens,
 * until an answer replaces it. */
function useChains(pathname) {
  const [health, setHealth] = useState(null)
  const [nudge, setNudge] = useState(0)
  const down = health?.status === 'down'
  useEffect(() => { if (down) setNudge((n) => n + 1) }, [pathname]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    let live = true
    let timer
    const ask = (miss) => fetchChains().then((h) => live && setHealth(h)).catch(() => {
      if (!live) return
      setHealth({ status: 'down' })
      timer = setTimeout(() => ask(miss + 1), Math.min(60_000, 2_000 * 2 ** miss))
    })
    ask(0)
    return () => { live = false; clearTimeout(timer) }
  }, [nudge])
  return health
}

export default function AppShell() {
  // The router reads /cases/ as /cases; so do the sidebar and breadcrumbs.
  const pathname = useLocation().pathname.replace(/(.)\/+$/, '$1')
  const out = useWayOut(useDemoView('investigator'))
  const { officer } = out
  const health = useChains(pathname)
  const still = useMedia(STILL)
  const intro = useIntro(still)
  const nav = useRef(null)
  const pill = useNavPill(nav, `${pathname} ${out.admin}`)
  const [named, setNamed] = useState(null)
  const crumbs = trail(pathname)
  if (named && crumbs.length > 1) crumbs[crumbs.length - 1] = { label: named, mono: true }
  // Each page its own title, most specific first: "Cases · Exchequer",
  // "0xabc…1234 · Cases · Exchequer". Leaving the console puts the site's back.
  const title = crumbs.length ? [...crumbs.map((c) => c.label).reverse(), 'Exchequer'].join(' · ') : null
  useEffect(() => {
    if (!title) return undefined
    const before = document.title
    document.title = title
    return () => { document.title = before }
  }, [title])

  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to the page</a>
      <aside className={`shell-side${intro ? ' intro' : ''}`} aria-label="Sidebar">
        {intro && <span className="shell-sheen" aria-hidden="true" />}
        <div className="shell-brand">
          <Mark size={20} />
          <span>
            <Link to="/" className="shell-name">Exchequer</Link>
            {officer
              ? <small className="shell-who"><span>{plain(officer.name)}</span><span>{plain(officer.unit?.name)}</span></small>
              : <small>Demo mode · {out.view.name}</small>}
          </span>
        </div>
        <div className="shell-demo">
          <WayOut out={out} />
        </div>
        <nav ref={nav} aria-label="Main" className={`shell-nav${pill ? ' has-pill' : ''}`}>
          {pill && (
            <span aria-hidden="true" data-on={pill.to} className={`shell-pill${pill.glide && !still ? ' glide' : ''}`}
              style={{ transform: `translateY(${pill.top}px)`, height: pill.height }} />
          )}
          {(out.admin ? [...GROUPS, ADMIN_GROUP] : GROUPS).map(([group, items]) => (
            <div key={group}>
              <span className="shell-group" id={`shell-${group}`}>{group}</span>
              <ul aria-labelledby={`shell-${group}`}>
                {items.map((item) => (
                  <li key={item.to} style={intro ? { '--i': Math.min(ITEMS.indexOf(item), STAGGER_STEPS) } : undefined}>
                    <Link className="shell-link" to={item.to} aria-current={where(item, pathname)}><Icon name={item.icon} />{item.label}</Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <Status health={health} />
      </aside>
      <div className="shell-body">
        <header className="shell-head">
          {crumbs.length > 0 && (
            <nav aria-label="Breadcrumb" className="shell-crumbs">
              <ol>
                {crumbs.map((c, i) => (
                  <li key={c.label}>
                    {i > 0 && <span aria-hidden="true">/</span>}
                    {c.to ? <Link to={c.to}>{c.label}</Link> : <span aria-current="page" className={c.mono ? 'mono' : undefined}>{c.label}</span>}
                  </li>
                ))}
              </ol>
            </nav>
          )}
          <span className="grow" />
          <Find health={health} path={pathname} />
          <ThemeToggle />
        </header>
        <main id="main" className="shell-main" tabIndex={-1}>
          <Crumb.Provider value={setNamed}><Suspense fallback={null}><Outlet /></Suspense></Crumb.Provider>
        </main>
      </div>
      <PhoneBar path={pathname} out={out} />
    </div>
  )
}
