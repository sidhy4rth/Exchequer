import { useEffect, useState } from 'react'
import { fetchAccess, fetchChains, fetchExchanges, fetchRiskLabels } from '../api'
import ChainDot, { chainColour } from '../components/ChainDot'
import Showroom from '../components/Showroom'
import TraceForm, { SHORT_CHAIN } from '../components/TraceForm'
import GlobeBackground from '../components/GlobeBackground'
import { hasDemoAccess } from '../demoCode'

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

// The console's first page (/): the trace form, the flagged addresses every
// hop is screened against, and, one click away, what the label files cover.
// The shell (AppShell) carries the name, the pages and the chain status; the
// stored cases, watchlist, requests and bulk intake are pages of their own
// (Work).
export default function Home() {
  const [health, setHealth] = useState(null)
  const [coverage, setCoverage] = useState({})
  // Whether this site asks for an access code (backend/app/access.py). Until it
  // answers, or if it cannot, the form shows: the backend refuses a trace
  // without the code either way, so the worst case is its message.
  const [access, setAccess] = useState(null)
  const [unlocked, setUnlocked] = useState(() => hasDemoAccess())

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
  const backendDown = health?.status === 'down'
  // A public site without the code: verified examples only, nothing that would
  // spend the provider quota.
  const locked = Boolean(access?.demo_code_required) && !unlocked

  // Flagged addresses per chain: the risk-label count (label files plus the
  // label store), from /risk-labels once it answers, /chains until then.
  const flaggedOf = (c) => coverage[c.key]?.risk?.count ?? Object.values(c.risk_labels ?? {}).reduce((a, b) => a + (b || 0), 0)
  const perChain = chains.map((c) => ({ ...c, flagged: flaggedOf(c) })).sort((a, b) => b.flagged - a.flagged)
  const totalFlagged = perChain.reduce((s, c) => s + c.flagged, 0)
  const top = perChain[0]?.flagged || 1

  return (
    <div className="home console">
      <GlobeBackground />
      <div className="home-body">
        <h1 className="visually-hidden">Console</h1>
        <section className="intake">
          <div className="intake-form">
            {locked ? <Showroom onUnlock={() => setUnlocked(true)} /> : <TraceForm health={health} />}
          </div>

          <div className="card glass flagged-card" role="group" aria-label="Flagged addresses screened">
            <div className="body">
              <div className="flagged-total">
                <strong>{health && !backendDown ? compact.format(totalFlagged) : '—'}</strong>
                <span>flagged addresses</span>
              </div>
              <span className="mono exact">{health && !backendDown ? `${totalFlagged.toLocaleString('en')} · screened on every hop` : backendDown ? 'Backend unreachable' : 'Connecting…'}</span>
              <ul className="chain-bars">
                {perChain.map((c) => (
                  <li key={c.key}>
                    <span className="name" title={c.name}><ChainDot chain={c.key} />{SHORT_CHAIN[c.key] ?? c.name}</span>
                    <span className="n mono">{c.flagged.toLocaleString('en')}</span>
                    <span className="bar" aria-hidden="true"><i style={{ width: `${Math.max(1.5, (c.flagged / top) * 100)}%`, background: chainColour(c.key) }} /></span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        {/* Closed until asked for: the console opens on the form and the
            flagged addresses, as it did when this was a tab. */}
        <details className="card glass sec" aria-label="Coverage">
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
                      <td className="num">{coverage[c.key]?.risk?.counts_by_category?.mixer ?? c.risk_labels?.mixer ?? 0}</td>
                      <td className="num">{coverage[c.key]?.risk?.counts_by_category?.frozen ?? c.risk_labels?.frozen ?? 0}</td>
                      <td className="num">{coverage[c.key]?.risk?.counts_by_category?.stolen ?? c.risk_labels?.stolen ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="note" style={{ padding: '8px 14px' }}>Every mixer on the current SDN list is a Bitcoin service, so the count is zero; the stop-at-a-mixer rule is built and tested.</p>
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

      <footer className="foot">
        <span>Names an exchange, never a person.</span>
      </footer>
    </div>
  )
}
