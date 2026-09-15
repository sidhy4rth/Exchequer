import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchCases, fetchExchanges, fetchHealth, fetchRiskLabels } from '../api'

// Same rules the backend enforces, checked here only so an obvious typo gets
// immediate feedback instead of a round trip. The backend remains the
// authority. Ethereum and BSC share the EVM 0x format; Tron uses
// case-sensitive Base58 beginning with T.
const ADDRESS_RE = {
  evm: /^0x[0-9a-fA-F]{40}$/,
  tron: /^T[1-9A-HJ-NP-Za-km-z]{33}$/,
}

// The ten verified traces in DEMO.md, one click each. Addresses and hooks
// are copied from that file; the numbers there were measured cold on
// 15 September 2026.
const DEMOS = [
  { n: '01', address: '0x7c3e9bab6715e4040f013e865b193b0209642e36', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'No cash-out found', hook: 'Three hops, no exchange, no pattern. The score reads "not applicable", not 0 — finding nothing is a result.' },
  { n: '02', address: '0xbc1ada2e98dd0087cf4cc0c8bd0e6276c82fadc9', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'A pattern, but no cash-out', hook: 'An amount split fires with its thresholds printed; the money never reaches a labelled exchange.' },
  { n: '03', address: '0x536c4921d1aafde6a5cda882fb5ca046f3601c65', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'The attribution that was lost', hook: 'Reached Binance at 0.65 a week ago; with the time rule, 643 pre-arrival transfers are excluded and no exchange remains.' },
  { n: '04', address: '0x536c4921d1aafde6a5cda882fb5ca046f3601c65', chain: 'ethereum', asset: 'ETH', depth: 1, direction: 'incoming',
    title: 'Who paid the offender', hook: 'The same wallet asked the other question: ten addresses funded it, none an exchange — ten candidate complaints.' },
  { n: '05', address: '0x60d02e0956e2f3795167c15ba61ab452c85c2533', chain: 'ethereum', asset: 'ETH', depth: 1, direction: 'incoming',
    title: 'Why funders are labelled carefully', hook: 'Nine funders, six of them exchange withdrawals marked as such. A tool counting "nine victims" would be wrong by three.' },
  { n: '06', address: '0x00000000072d54638c2c2a3da3f715360269eea1', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'The deposit address to name', hook: 'A phishing-labelled wallet whose funds reach a probable Binance deposit address — inferred, scored lower, evidence attached.' },
  { n: '07', address: '0x21b8d56bda776bbe68655a16895afd96f5534fed', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'A sanctioned wallet', hook: 'The reported address is on the OFAC SDN list; its funds reach a probable Bybit deposit address still holding 1.2 ETH.' },
  { n: '08', address: '0x4655b7ad0b5f5bacb9cf960bbffceb3f0e51f363', chain: 'ethereum', asset: 'ETH', depth: 2, direction: 'outgoing',
    title: 'The trail changes asset', hook: '2,000 ETH into 1inch, returned as wstETH. The swap is read from the receipt; the trace says where to re-run.' },
  { n: '09', address: 'THWYhwUQnBcKpwSxaXjqv18RPtSoK4C5Ph', chain: 'tron', asset: 'USDT', depth: 2, direction: 'outgoing',
    title: 'Tron, in under a second', hook: 'USDT-TRC20 to Binance-Hot 7 in one hop, 26,405 USDT, confidence 1.00 — against 40 verified Tron labels.' },
  { n: '10', address: '0x000000000532b45f47779fce440748893b257865', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'Three complaints, one operation', hook: 'Shares 61 intermediaries with two other stored phishing wallets, four of them inferred Binance deposit addresses.' },
]

const middle = (a, head = 10, tail = 8) => (a && a.length > head + tail + 1 ? `${a.slice(0, head)}…${a.slice(-tail)}` : a)

export default function Home() {
  const navigate = useNavigate()
  const [health, setHealth] = useState(null)
  const [cases, setCases] = useState([])
  const [coverage, setCoverage] = useState({})
  const [address, setAddress] = useState('')
  const [chain, setChain] = useState('ethereum')
  const [asset, setAsset] = useState('ETH')
  const [depth, setDepth] = useState(4)
  const [direction, setDirection] = useState('outgoing')
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        setHealth(h)
        if (h.default_chain) {
          setChain(h.default_chain)
          setAsset(h.chains?.[h.default_chain]?.assets?.[0]?.symbol ?? 'ETH')
        }
        // Coverage per chain: what the label files and screening lists hold.
        Object.keys(h.chains ?? {}).forEach((key) => {
          Promise.all([fetchExchanges(key), fetchRiskLabels(key)])
            .then(([ex, risk]) => setCoverage((c) => ({ ...c, [key]: { exchanges: ex, risk } })))
            .catch(() => {})
        })
      })
      .catch(() => setHealth({ status: 'down' }))
    fetchCases(12).then((d) => setCases(d.cases)).catch(() => {})
  }, [])

  const chains = health?.chains ? Object.values(health.chains) : []
  const active = health?.chains?.[chain]
  const assets = active?.assets ?? []
  const family = active?.address_family ?? 'evm'
  const backendDown = health?.status === 'down'

  const trimmed = address.trim()
  const valid = (ADDRESS_RE[family] ?? ADDRESS_RE.evm).test(trimmed)
  const showInvalid = touched && trimmed.length > 0 && !valid

  // Switching chain resets the asset: BNB does not exist on Ethereum, so the
  // symbol cannot be carried across.
  const changeChain = useCallback((next) => {
    setChain(next)
    setAsset(health?.chains?.[next]?.assets?.[0]?.symbol ?? 'ETH')
  }, [health])

  const open = useCallback((addr, opts = {}) => {
    const q = new URLSearchParams({
      chain: opts.chain ?? chain, asset: opts.asset ?? asset,
      depth: String(opts.depth ?? depth), direction: opts.direction ?? direction,
    })
    navigate(`/trace/${addr}?${q}`)
  }, [navigate, chain, asset, depth, direction])

  function submit(event) {
    event.preventDefault()
    setTouched(true)
    if (valid) open(trimmed)
  }

  const totalLabels = chains.reduce((sum, c) => sum + (c.exchange_labels || 0), 0)

  return (
    <div className="home">
      <header className="topbar">
        <Link to="/" className="brand">TraceChain<small>Cryptocurrency fraud tracing</small></Link>
        <span className="grow" />
        <span className="note">Smart India Hackathon 2026 · SIH26183 · Ministry of Home Affairs</span>
      </header>

      <div className="home-body">
        <section className="intake">
          <div className="card">
            <div className="body">
              <p className="lede">Follow a reported wallet's money to the exchange it left through — as evidence an officer can attach to a request.</p>
              <p className="note">
                Every attribution is an exact match against a published exchange label, or an inference that says so and scores lower. Every pattern prints the thresholds it applied. The tool states what it did not look at. It names an exchange, never a person.
              </p>
              <form onSubmit={submit}>
                <div className="row">
                  <input
                    className={`address-field ${showInvalid ? 'invalid' : ''}`}
                    value={address}
                    onChange={(e) => setAddress(e.target.value)}
                    onBlur={() => setTouched(true)}
                    placeholder={`Reported wallet address (${family === 'tron' ? 'T…' : '0x…'})`}
                    spellCheck={false} autoComplete="off"
                    aria-label="Reported wallet address" aria-invalid={showInvalid}
                  />
                  <select value={direction} onChange={(e) => setDirection(e.target.value)} aria-label="Trace direction" title="Outgoing follows where this address sent funds. Incoming finds the addresses that paid it.">
                    <option value="outgoing">Where funds went</option>
                    <option value="incoming">Who sent funds here</option>
                  </select>
                  <select value={chain} onChange={(e) => changeChain(e.target.value)} aria-label="Blockchain" title="The same address can exist on several chains; it is never inferred.">
                    {chains.map((c) => <option key={c.key} value={c.key} disabled={!c.ready}>{c.name}{c.ready ? '' : ' — unavailable'}</option>)}
                  </select>
                  <select value={asset} onChange={(e) => setAsset(e.target.value)} aria-label="Asset" title="One asset per trace — amounts in different assets are not comparable.">
                    {assets.map((a) => <option key={a.symbol} value={a.symbol}>{a.symbol}</option>)}
                  </select>
                  <select value={depth} onChange={(e) => setDepth(Number(e.target.value))} aria-label="Trace depth" title="How many hops to follow. More finds more and takes longer.">
                    {[1, 2, 3, 4, 5, 6].map((d) => <option key={d} value={d}>{d} hop{d === 1 ? '' : 's'}</option>)}
                  </select>
                  <button type="submit" className="primary" disabled={!valid || backendDown}>
                    {direction === 'outgoing' ? 'Trace' : 'Trace back'}
                  </button>
                </div>
                {showInvalid && (
                  <div className="banner warn">
                    Not a valid {active?.name ?? 'wallet'} address — expected {family === 'tron' ? 'T followed by 33 Base58 characters' : '0x followed by 40 hexadecimal characters'}.
                  </div>
                )}
                {backendDown && (
                  <div className="banner error">Cannot reach the backend. Start it with <span className="mono">uvicorn app.main:app --reload --port 8000</span>.</div>
                )}
              </form>
            </div>
          </div>

          <div className="card">
            <div className="head"><span className="micro">Providers</span><span className="note">{health ? `${totalLabels} exchange labels` : ''}</span></div>
            <div className="body status">
              {!health && <span className="note">Connecting…</span>}
              {backendDown && <div className="line"><span className="dot down" /><span>Backend unreachable</span><span /></div>}
              {chains.map((c) => (
                <div className="line" key={c.key}>
                  <span className={`dot ${c.ready ? 'live' : 'down'}`} />
                  <span>{c.name} <span className="note">via {c.provider}</span></span>
                  <span className="n">{c.exchange_labels} labels · {(c.risk_labels?.sanctioned ?? 0) + (c.risk_labels?.mixer ?? 0)} screened</span>
                </div>
              ))}
              {health?.api_budget?.pacers && Object.values(health.api_budget.pacers).map((p, i) => (
                <div className="line" key={i}><span className="dot" /><span className="note">request pacing</span><span className="n">{p.interval}s · {p.rate_limit_penalties} refusals</span></div>
              ))}
            </div>
          </div>
        </section>

        <section>
          <div className="card">
            <div className="head"><span className="micro">Verified demonstrations · DEMO.md</span><span className="note">each opens a live trace; numbers measured cold on 15 September 2026</span></div>
            <div className="body">
              <div className="demos">
                {DEMOS.map((d) => (
                  <button key={d.n} type="button" className="demo" onClick={() => open(d.address, d)} disabled={backendDown} title={d.address}>
                    <span className="n">DEMO {d.n}</span>
                    <span className="t">{d.title}</span>
                    <span className="h">{d.hook}</span>
                    <span className="m">
                      <span className="pill">{d.chain === 'tron' ? 'Tron' : 'Ethereum'}</span>
                      <span className="pill mono">{d.asset}</span>
                      <span className="pill mono">{d.depth} hop{d.depth === 1 ? '' : 's'}</span>
                      {d.direction === 'incoming' && <span className="pill navy">reverse</span>}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="coverage">
          <div className="card">
            <div className="head"><span className="micro">Exchange labels</span><span className="note">exact-match attribution</span></div>
            <table>
              <thead><tr><th>Chain</th><th style={{ textAlign: 'right' }}>Wallets</th><th>Exchanges</th></tr></thead>
              <tbody>
                {chains.map((c) => (
                  <tr key={c.key}>
                    <td>{c.name}</td>
                    <td className="num">{coverage[c.key]?.exchanges?.count ?? c.exchange_labels}</td>
                    <td className="exchanges">{coverage[c.key]?.exchanges?.exchanges?.join(', ') ?? '…'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card">
            <div className="head"><span className="micro">Sanctions and mixer screening</span><span className="note">OFAC SDN list</span></div>
            <table>
              <thead><tr><th>Chain</th><th style={{ textAlign: 'right' }}>Sanctioned</th><th style={{ textAlign: 'right' }}>Mixers</th><th>Screened</th></tr></thead>
              <tbody>
                {chains.map((c) => (
                  <tr key={c.key}>
                    <td>{c.name}</td>
                    <td className="num">{coverage[c.key]?.risk?.counts_by_category?.sanctioned ?? c.risk_labels?.sanctioned ?? 0}</td>
                    <td className="num">{coverage[c.key]?.risk?.counts_by_category?.mixer ?? c.risk_labels?.mixer ?? 0}</td>
                    <td>{(coverage[c.key]?.risk?.screened ?? (c.risk_labels?.sanctioned > 0)) ? 'yes' : 'no'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="note" style={{ padding: '8px 14px' }}>The mixer count is zero because every mixer on the current SDN list is a Bitcoin service; the stop-at-a-mixer rule is built and tested.</p>
          </div>
          <div className="card">
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
        </section>

        <section>
          <div className="card">
            <div className="head"><span className="micro">Stored cases · {cases.length}</span><span className="note">evidence as it stood when it was taken; opening one does not re-trace</span></div>
            {cases.length === 0 ? <p className="note" style={{ padding: 12 }}>No stored cases yet.</p> : (
              <table className="cases-table">
                <thead><tr><th>Reported address</th><th>Chain</th><th>Asset</th><th>Result</th><th style={{ textAlign: 'right' }}>Confidence</th><th style={{ textAlign: 'right' }}>Addresses</th><th>Flags</th><th>Traced</th></tr></thead>
                <tbody>
                  {cases.map((c) => (
                    <tr className="row" key={c.case_id} onClick={() => navigate(`/case/${c.case_id}`)} title={`Open stored case for ${c.address}`}>
                      <td className="mono">{middle(c.address, 12, 10)}</td>
                      <td>{c.chain}</td>
                      <td className="mono">{c.asset ?? '—'}</td>
                      <td className={c.exchange ? '' : 'none'}>{c.exchange ?? 'no match'}</td>
                      <td className="num">{c.confidence == null ? 'n/a' : c.confidence.toFixed(2)}</td>
                      <td className="num">{c.node_count}</td>
                      <td>{(c.flags ?? []).map((f) => <span className="pill amber" key={f} style={{ marginRight: 4 }}>{f.replace('_', ' ')}</span>)}</td>
                      <td className="mono">{String(c.created_at).slice(0, 10)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </div>

      <footer className="foot">
        <span>Attribution identifies an exchange, never a person. Only the exchange can link an address to a customer, on a lawful request.</span>
        <span>{health ? `${chains.filter((c) => c.ready).length} chains ready` : ''}</span>
      </footer>
    </div>
  )
}
