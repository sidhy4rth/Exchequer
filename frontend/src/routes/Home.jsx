import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchAccess, fetchCases, fetchChains, fetchExchanges, fetchRecordedDemos, fetchRiskLabels, fetchWatches } from '../api'
import ChainDot from '../components/ChainDot'
import Showroom from '../components/Showroom'
import { DEMOS, SHORT_CHAIN } from '../components/TraceForm'
import { bandLabel, bandOf } from '../components/confidence'
import { hasDemoAccess, liveLock } from '../demoCode'
import { ADDRESS_RE, HASH_RE, findTarget } from '../find'
import { useMedia, usePhone } from '../phone'
import { plain } from '../text'
import './Home.css'

// The console's first page (/): one field to start from (a victim's payment
// hash or the wallet they paid), three recorded cases to try, this browser's
// recent cases, the exchange wallets a trace can name, and the watchlist.
// The shell (AppShell) carries the pages and the chain status; the trace
// form with every option is New trace (Work). Every figure is the backend's.

// From DEMO.md's list: Tron to Binance, Tron to an exchange the label file
// did not know, Ethereum to Bybit.
const TRY = ['11', '12', '07']
const nameOf = (key, chain) => SHORT_CHAIN[key] ?? chain?.name ?? key
const count = (n) => n.toLocaleString('en')
const and = new Intl.ListFormat('en', { type: 'conjunction' })

// The field's hint: the pack's sentence, or on a phone, where the field holds
// about 38 characters, its label.
const HINT = "Victim's payment hash, or the wallet they paid"

// Motion (Home.css): the cards rise in one after another, the hint types
// itself in once, and a few slow loops (the hero's edge, the status dot, the
// empty watchlist's radar, the glow behind the page) run until paused. With
// reduced motion asked for, every one of them is drawn at its final state.
const REDUCED = '(prefers-reduced-motion: reduce)'
const PAUSE_KEY = 'exchequer-console-motion'
const STAGGER_STEPS = 8
/** A section's place in the entrance, capped so the last never waits long. */
const rise = (n) => ({ '--rise': Math.min(n, STAGGER_STEPS) })

function savedPause() {
  try { return localStorage.getItem(PAUSE_KEY) === 'paused' } catch { return false }
}

/** The field's hint, typed in once a character at a time, over an empty
 * field only. Drawn for the eye alone: the field keeps its label and its
 * placeholder, and nothing here takes a click or a key. */
function TypedHint({ text }) {
  return (
    <span className="hero-typed" aria-hidden="true">
      {[...text].map((ch, i) => <span key={i} style={{ '--i': i }}>{ch}</span>)}
    </span>
  )
}

/** Each ready chain's assets as one choice, "Tron · USDT". On Tron USDT
 * comes first: the money in a complaint is almost always USDT. */
function choices(health) {
  return Object.values(health?.chains ?? {}).filter((c) => c.ready).flatMap((c) => {
    const family = c.address_family ?? 'evm'
    const symbols = (c.assets ?? []).map((a) => a.symbol)
    const first = family === 'tron' && symbols.includes('USDT') ? ['USDT'] : []
    return [...first, ...symbols.filter((s) => !first.includes(s))]
      .map((asset) => ({ value: `${c.key}:${asset}`, chain: c.key, asset, family, label: `${nameOf(c.key, c)} · ${asset}` }))
  })
}

/** A wallet or a payment hash, with the address family that must read it
 * (null for a 0x hash, which any chain's format allows); else null. */
function read(text) {
  const q = text.trim()
  const family = ADDRESS_RE.evm.test(q) ? 'evm' : ADDRESS_RE.tron.test(q) ? 'tron' : null
  if (family) return { q, wallet: true, family }
  if (HASH_RE.tron.test(q)) return { q, wallet: false, family: q.startsWith('0x') ? null : 'tron' }
  return null
}

/** The hero's field. A wallet opens its trace link, which shows what it
 * would run and waits for a click; a payment hash fills the new trace form,
 * which still needs the wallet the victim paid. Paste a Tron wallet with an
 * Ethereum choice and the choice moves to Tron. */
function QuickTrace({ health }) {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [picked, setPicked] = useState(null)
  const [missed, setMissed] = useState(false)
  const phone = usePhone()
  const hint = phone ? 'Payment hash or wallet' : HINT
  const options = choices(health)
  const chosen = options.find((o) => o.value === picked) ?? options.find((o) => o.chain === health?.default_chain) ?? options[0]

  function change(value) {
    setText(value)
    setMissed(false)
    const family = read(value)?.family
    const fits = family && chosen?.family !== family && options.find((o) => o.family === family)
    if (fits) setPicked(fits.value)
  }

  function submit(event) {
    event.preventDefault()
    if (!text.trim()) return
    const got = read(text)
    if (!got) { setMissed(true); return }
    // No ready chain reads it: the shell search's choice, which the trace page checks.
    if (!chosen || (got.family && chosen.family !== got.family)) { navigate(findTarget(got.q, health)); return }
    const on = new URLSearchParams({ chain: chosen.chain, asset: chosen.asset })
    navigate(got.wallet ? `/trace/${got.q}?${on}` : `/trace/new?${new URLSearchParams({ pay: got.q })}&${on}`)
  }

  return (
    <form className="hero-trace" onSubmit={submit} noValidate>
      <div className="hero-field">
        <svg aria-hidden="true" width="17" height="17" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"><circle cx="7" cy="7" r="5" /><path d="M11 11l3.5 3.5" /></svg>
        <label htmlFor="console-find" className="visually-hidden">Payment hash or wallet</label>
        <span className="hero-input">
          <input id="console-find" value={text} onChange={(e) => change(e.target.value)} spellCheck={false} autoComplete="off"
            placeholder={hint}
            aria-invalid={missed || undefined} aria-describedby={missed ? 'console-find-missed' : undefined} />
          <TypedHint key={hint} text={hint} />
        </span>
      </div>
      <label htmlFor="console-chain" className="visually-hidden">Chain and asset</label>
      <span className="hero-chain">
        <select id="console-chain" value={chosen?.value ?? ''} onChange={(e) => setPicked(e.target.value)} disabled={!options.length}>
          {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <svg aria-hidden="true" width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M2 3.5l3 3 3-3" /></svg>
      </span>
      <button type="submit" className="primary">
        Trace
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 7h10M8 3l4 4-4 4" /></svg>
      </button>
      {missed && <p id="console-find-missed" className="hero-missed" role="alert">Not recognised: paste the victim's payment hash, or the wallet they paid.</p>}
    </form>
  )
}

/** Three recorded cases, named from what each recording found (an inferred
 * exchange as a probable deposit); one the site holds no recording of is not
 * offered. */
function TryRecorded() {
  const [recorded, setRecorded] = useState([])
  useEffect(() => { fetchRecordedDemos().then((d) => setRecorded(d.demos ?? [])).catch(() => {}) }, [])
  const tries = TRY.map((n) => [DEMOS.find((d) => d.n === n), recorded.find((r) => r.demo === Number(n))]).filter(([d, r]) => d && r)
  return (
    <div className="hero-try">
      {tries.length > 0 && <span id="hero-try">Try a recorded case</span>}
      {tries.length > 0 && (
        <ul aria-labelledby="hero-try">
          {tries.map(([d, r]) => (
            <li key={d.n}><Link to={`/demo/${r.demo}`}>{!r.exchange ? d.title
              : `${nameOf(d.chain)} ${d.asset} to ${r.attribution_inferred ? `a probable ${plain(r.exchange)} deposit` : plain(r.exchange)}`}</Link></li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** This browser's newest cases, and the recorded demos the site keeps
 * (marked as such): what each reached, and how sure, as the band word. */
function RecentCases() {
  // undefined while asking; null when the cases cannot be reached.
  const [cases, setCases] = useState(undefined)
  useEffect(() => { fetchCases(5).then((d) => setCases(d.cases ?? [])).catch(() => setCases(null)) }, [])
  return (
    <section className="card glass console-card console-rise" style={rise(3)} aria-labelledby="console-recent">
      <div className="console-card-head"><h2 id="console-recent">Recent cases</h2><Link to="/cases">All cases</Link></div>
      {cases === undefined && <p className="note" role="status">Loading cases…</p>}
      {cases?.length === 0 && <p className="note">No cases yet. Cases you trace show here, in this browser only.</p>}
      {cases === null && <p className="note">Recent cases cannot be reached right now.</p>}
      {cases?.length > 0 && (
        <ul className="recent-cases">
          {cases.map((c) => {
            const meta = [[nameOf(c.chain), c.asset].filter(Boolean).join(' '), c.hop_count != null && `${c.hop_count} hop${c.hop_count === 1 ? '' : 's'}`,
              c.direction === 'incoming' && 'reverse'].filter(Boolean).join(' · ')
            const band = bandOf(c.confidence)
            return (
              <li key={c.case_id}>
                <Link to={`/case/${c.case_id}`}>
                  <span className="mono recent-address">{c.address}</span>
                  <span className="recent-meta">{meta}{c.demo && <> <span className="pill">demo</span></>}</span>
                  <span className={`recent-reached${c.exchange ? '' : ' none'}`}><i aria-hidden="true" />{c.exchange ? plain(c.exchange) : 'No exchange'}</span>
                  {band && <span className={`recent-band ${band.replace(' ', '-')}`}><span className="visually-hidden">Confidence </span>{bandLabel(band)}</span>}
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

/** The exchanges' own wallets per chain (GET /chains), largest first. A
 * customer's deposit address is counted apart: it names one account. */
function ExchangeWallets({ health }) {
  const chains = Object.values(health?.chains ?? {}).filter((c) => typeof c.exchange_wallets === 'number')
    .sort((a, b) => b.exchange_wallets - a.exchange_wallets)
  const top = chains[0]?.exchange_wallets || 1
  const deposits = chains.filter((c) => c.deposit_addresses > 0).map((c) => `${count(c.deposit_addresses)} ${nameOf(c.key, c)}`)
  return (
    <section className="card glass console-card console-rise" style={rise(4)} aria-labelledby="console-wallets">
      <div className="console-card-head">
        <h2 id="console-wallets">Exchange wallets on file</h2>
        {chains.length > 0 && <span className="console-figure">{count(chains.reduce((s, c) => s + c.exchange_wallets, 0))}</span>}
      </div>
      {chains.length === 0 && <p className="note">{health?.status === 'down' ? 'Backend unreachable' : 'Connecting…'}</p>}
      {chains.length > 0 && (
        <ul className="wallet-bars" aria-label="Exchange wallets per chain">
          {chains.map((c, i) => (
            <li key={c.key}>
              <span>{nameOf(c.key, c)}</span>
              <span className="bar" aria-hidden="true"><i style={{ width: `${Math.max(1.5, (c.exchange_wallets / top) * 100)}%`, '--i': Math.min(i, STAGGER_STEPS) }} /></span>
              <span className="num">{count(c.exchange_wallets)}</span>
            </li>
          ))}
        </ul>
      )}
      {deposits.length > 0 && <p className="note">plus {and.format(deposits)} deposit addresses</p>}
    </section>
  )
}

/** How many wallets this browser watches, or how to start. */
function WatchCard() {
  // undefined while asking; null when the watchlist cannot be reached.
  const [watched, setWatched] = useState(undefined)
  useEffect(() => { fetchWatches().then((d) => setWatched(d.count ?? d.watches?.length ?? 0)).catch(() => setWatched(null)) }, [])
  return (
    <section className={`card glass console-card console-rise${watched ? '' : ' quiet-card'}`} style={rise(5)} aria-labelledby="console-watch">
      <div className="console-card-head"><h2 id="console-watch">Watchlist</h2>{watched > 0 && <span className="console-figure">{count(watched)}</span>}</div>
      {watched === 0 && (
        <div className="watch-empty">
          {/* Listening, with nothing to hear yet. */}
          <span className="watch-radar" aria-hidden="true"><i className="radar-sweep" /><i className="radar-ping" /><i className="radar-dot" /></span>
          <p className="note">Nothing watched yet. Watch a wallet from any case to hear when money moves.</p>
        </div>
      )}
      {watched === null && <p className="note">The watchlist cannot be reached right now.</p>}
      {watched > 0 && <p className="note">{`${watched} ${watched === 1 ? 'wallet' : 'wallets'} watched.`} <Link to="/watchlist">Open the watchlist</Link></p>}
    </section>
  )
}

export default function Home() {
  const [health, setHealth] = useState(null)
  const [coverage, setCoverage] = useState({})
  // Whether this site asks for an access code (backend/app/access.py). Until it
  // answers, or if it cannot, the field shows: the backend refuses a trace
  // without the code either way, so the worst case is its message.
  const [access, setAccess] = useState(null)
  const [unlocked, setUnlocked] = useState(() => hasDemoAccess())
  const reduced = useMedia(REDUCED)
  const [paused, setPaused] = useState(savedPause)

  function togglePause() {
    const next = !paused
    setPaused(next)
    try { if (next) localStorage.setItem(PAUSE_KEY, 'paused'); else localStorage.removeItem(PAUSE_KEY) } catch { /* private mode */ }
  }

  // Every path out of this page leads to a trace; fetch that page's code
  // (the graph layout is most of it) before the button is pressed.
  useEffect(() => { import('./TraceView') }, [])

  useEffect(() => {
    fetchChains()
      .then((h) => {
        setHealth(h)
        // Coverage per chain: what the label files and screening lists hold.
        Object.keys(h.chains ?? {}).forEach((key) => {
          Promise.all([fetchExchanges(key), fetchRiskLabels(key)])
            .then(([ex, risk]) => setCoverage((c) => ({ ...c, [key]: { exchanges: ex, risk } })))
            .catch(() => {})
        })
      })
      .catch(() => setHealth({ status: 'down' }))
    fetchAccess().then(setAccess).catch(() => setAccess({ demo_code_required: false }))
  }, [])

  const chains = health?.chains ? Object.values(health.chains) : []
  const allReady = chains.length > 1 && chains.every((c) => c.ready)
  const mixerCount = (c) => coverage[c.key]?.risk?.counts_by_category?.mixer ?? c.risk_labels?.mixer ?? 0
  // Explorer tags list mixers on some chains; the SDN list's are on Bitcoin.
  const mixers = chains.some((c) => mixerCount(c) > 0)
  // A public site without the code: verified examples only, nothing that would
  // spend the provider quota or keep running.
  // A site closed to officers: the same, until an officer signs in.
  const lock = liveLock(access, unlocked)
  const locked = Boolean(lock)

  return (
    <div className={`home console console-home${reduced ? ' still' : ''}${paused ? ' paused' : ''}`}>
      <div className="console-ambient" aria-hidden="true"><i /></div>
      <div className="home-body">
        <div className="hero">
          <div className="hero-top console-rise" style={rise(0)}>
            {allReady && <p className="hero-status"><i aria-hidden="true" />{`All ${chains.length} chains ready to trace`}</p>}
            {!reduced && (
              <button type="button" className="motion-toggle" aria-pressed={paused} onClick={togglePause}>
                <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                  {paused ? <path d="M3 1.8v8.4L10 6z" /> : <path d="M3 2h2v8H3zM7 2h2v8H7z" />}
                </svg>
                Pause motion
              </button>
            )}
          </div>
          <h1 className="console-rise blur" style={rise(1)}>Follow a payment to the exchange that can freeze it</h1>
        </div>
        {locked ? <Showroom officers={lock === 'officer'} onUnlock={() => setUnlocked(true)} /> : (
          <section className="card glass hero-card console-rise" style={rise(2)} aria-label="Start a trace">
            <QuickTrace health={health} />
            <TryRecorded />
          </section>
        )}

        <div className="console-grid">
          <RecentCases />
          <div className="console-side">
            <ExchangeWallets health={health} />
            {!locked && <WatchCard />}
          </div>
        </div>

        {/* Closed until asked for: the detail behind the wallets on file. */}
        <details className="card glass sec console-rise" style={rise(6)} aria-label="Coverage">
          <summary><span className="micro">Coverage</span><span className="note">Exchange labels and risk screening per chain</span></summary>
          <div className="coverage">
            <div>
              <div className="head"><span className="micro">Exchange labels</span><span className="note">exact-match attribution</span></div>
              <table tabIndex={0} aria-label="Exchange labels per chain">
                <thead><tr><th>Chain</th><th style={{ textAlign: 'right' }}>Exchange wallets</th><th style={{ textAlign: 'right' }}>Deposit addresses</th><th>Exchanges</th></tr></thead>
                <tbody>
                  {chains.map((c) => (
                    <tr key={c.key}>
                      <td title={c.name}><ChainDot chain={c.key} />{SHORT_CHAIN[c.key] ?? c.name}</td>
                      <td className="num">{c.exchange_wallets}</td>
                      <td className="num">{c.deposit_addresses}</td>
                      <td className="exchanges">{coverage[c.key]?.exchanges?.exchanges?.join(', ') ?? '…'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="note" style={{ padding: '8px 14px' }}>A deposit address belongs to one customer's account at the exchange. A match names the exchange that holds the account, never the customer: only the exchange can say whose it is.</p>
            </div>
            <div>
              <div className="head"><span className="micro">Risk screening</span><span className="note">US, UK, EU, Israel, Japan, France · Tether freezes · explorer-tagged hacks and mixers</span></div>
              <table tabIndex={0} aria-label="Risk screening per chain">
                <thead><tr><th>Chain</th><th style={{ textAlign: 'right' }}>Sanctioned or seized</th><th style={{ textAlign: 'right' }}>Mixers</th><th style={{ textAlign: 'right' }}>Frozen</th><th style={{ textAlign: 'right' }}>Stolen funds</th></tr></thead>
                <tbody>
                  {chains.map((c) => (
                    <tr key={c.key}>
                      <td title={c.name}><ChainDot chain={c.key} />{SHORT_CHAIN[c.key] ?? c.name}</td>
                      <td className="num">{(coverage[c.key]?.risk?.counts_by_category?.sanctioned ?? c.risk_labels?.sanctioned ?? 0) + (coverage[c.key]?.risk?.counts_by_category?.seized ?? c.risk_labels?.seized ?? 0)}</td>
                      <td className="num">{mixerCount(c)}</td>
                      <td className="num">{coverage[c.key]?.risk?.counts_by_category?.frozen ?? c.risk_labels?.frozen ?? 0}</td>
                      <td className="num">{coverage[c.key]?.risk?.counts_by_category?.stolen ?? c.risk_labels?.stolen ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="note" style={{ padding: '8px 14px' }}>{mixers
                ? "Mixers here are explorer-tagged; the SDN list's own mixers are Bitcoin services. A trace stops at a mixer's pool or entry point."
                : 'Every mixer on the current SDN list is a Bitcoin service, so these chains have none; the stop-at-a-mixer rule is built and tested.'}</p>
            </div>
            <div>
              <div className="head"><span className="micro">What a trace does</span></div>
              <div className="body">
                <div className="kv"><span className="k">Attribution</span><span className="v">exact label match, or a stated inference</span></div>
                <div className="kv"><span className="k">Patterns</span><span className="v">fixed arithmetic, thresholds printed</span></div>
                <div className="kv"><span className="k">Time rule</span><span className="v">only transfers after the funds arrived</span></div>
                <div className="kv"><span className="k">Stops at</span><span className="v">exchanges, mixers, routers, service contracts</span></div>
                <div className="kv"><span className="k">Score</span><span className="v">three weighted inputs; null when nothing matched</span></div>
                <div className="kv"><span className="k">Never</span><span className="v">a person, a model, a guess</span></div>
              </div>
            </div>
          </div>
        </details>
      </div>

      <footer className="foot console-rise" style={rise(7)}>
        <span>Names an exchange, never a person.</span>
      </footer>
    </div>
  )
}
