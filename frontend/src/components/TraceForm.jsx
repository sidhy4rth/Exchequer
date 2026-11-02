import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchRecordedDemos } from '../api'

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
    title: 'The pattern that stopped firing', hook: 'An amount split fired here on 15 Sep and not on 23 Sep — same rule, the chain moved. Why no pattern is ever scored.' },
  { n: '03', address: '0x536c4921d1aafde6a5cda882fb5ca046f3601c65', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'An attribution that keeps moving', hook: 'Changed six times on live data, each for a stated reason. Two days ago a weak OKX lead (≈ 1.65 of 951 ETH); now the wallet paid a Binance deposit address directly — 1 hop, 0.875.' },
  { n: '04', address: '0x536c4921d1aafde6a5cda882fb5ca046f3601c65', chain: 'ethereum', asset: 'ETH', depth: 1, direction: 'incoming',
    title: 'Who paid the offender', hook: 'The same wallet asked the other question: ten addresses funded it, none an exchange — ten candidate complaints.' },
  { n: '05', address: '0x60d02e0956e2f3795167c15ba61ab452c85c2533', chain: 'ethereum', asset: 'ETH', depth: 1, direction: 'incoming',
    title: 'Why funders are labelled carefully', hook: 'Ten funders, five of them exchange withdrawals marked as such. A tool counting "ten victims" would double the count.' },
  { n: '06', address: '0x00000000072d54638c2c2a3da3f715360269eea1', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'The deposit address to name', hook: 'A phishing wallet: funds reach a probable Binance deposit address — inferred, scored lower — and 10 ETH reach Tornado Cash, where the trace stops.' },
  { n: '07', address: '0x21b8d56bda776bbe68655a16895afd96f5534fed', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'Three governments, one wallet', hook: 'The reported address is on the US, UK and Israeli lists; its funds reach a probable Bybit deposit address.' },
  { n: '08', address: '0x4655b7ad0b5f5bacb9cf960bbffceb3f0e51f363', chain: 'ethereum', asset: 'ETH', depth: 2, direction: 'outgoing',
    title: 'The trail changes asset', hook: '2,000 ETH into 1inch, returned as wstETH. The swap is read from the receipt; the trace says where to re-run.' },
  { n: '09', address: 'THWYhwUQnBcKpwSxaXjqv18RPtSoK4C5Ph', chain: 'tron', asset: 'USDT', depth: 2, direction: 'outgoing',
    title: 'Tron, in under a second', hook: 'USDT-TRC20 to Binance-Hot 7 in one hop, 26,405 USDT, confidence 1.00 — against 41 verified Tron labels.' },
  { n: '10', address: '0x000000000532b45f47779fce440748893b257865', chain: 'ethereum', asset: 'ETH', depth: 3, direction: 'outgoing',
    title: 'Three complaints, one operation', hook: 'Shares 60 and 46 intermediaries with two other stored phishing wallets — and all three reach the same known phishing wallet.' },
  { n: '11', address: 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts', chain: 'tron', asset: 'USDT', depth: 2, direction: 'outgoing',
    title: 'Frozen by Tether', hook: 'A Tron wallet whose USDT Tether froze on 11 Sep 2026 — as it did the next wallet — splits 45,968 USDT onward; it reaches Binance-Hot 7 at 0.80.' },
  { n: '12', address: 'TB2KXtbmFJa8PaCPbRXrJrHkZSPU22eqja', chain: 'tron', asset: 'USDT', depth: 2, direction: 'outgoing',
    title: 'An exchange the file does not know', hook: 'Flipster is not among the 41 labelled Tron wallets; TronScan’s own tag, read live, names it at confidence 1.00.' },
]

// The optional wall-clock cap, in seconds. 1:30 is long enough for any of
// the demo traces cold and short enough to keep a room waiting comfortably.
const TIME_BUDGET_SECONDS = 90

/** The intake card: a reported address, how to trace it, and the DEMO.md
 * examples to fill it from. `health` is GET /health as the page loaded it
 * (null while connecting, { status: 'down' } when unreachable). */
export default function TraceForm({ health }) {
  const navigate = useNavigate()
  const [address, setAddress] = useState('')
  const [chain, setChain] = useState('ethereum')
  const [asset, setAsset] = useState('ETH')
  const [depth, setDepth] = useState(4)
  const [direction, setDirection] = useState('outgoing')
  // Off by default: the trace runs its full course. On, it stops at 1:30 and
  // reports what it reached -- for a live pick whose size nobody knows.
  const [capped, setCapped] = useState(false)
  const [touched, setTouched] = useState(false)
  // The demo last loaded into the form, and which demos have a recording.
  const [loadedDemo, setLoadedDemo] = useState(null)
  const [recordings, setRecordings] = useState({})

  // Trace on the deployment's default chain once /health names it.
  useEffect(() => {
    if (!health?.default_chain) return
    setChain(health.default_chain)
    setAsset(health.chains?.[health.default_chain]?.assets?.[0]?.symbol ?? 'ETH')
  }, [health])

  useEffect(() => {
    fetchRecordedDemos()
      .then((d) => setRecordings(Object.fromEntries(d.demos.map((r) => [r.demo, r]))))
      .catch(() => {})
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
    if (opts.capped ?? capped) q.set('budget', String(TIME_BUDGET_SECONDS))
    navigate(`/trace/${addr}?${q}`)
  }, [navigate, chain, asset, depth, direction, capped])

  // Fill the form from one of the verified DEMO.md traces. The trace is not
  // started: the officer still presses the same button they would for a real
  // address, so the demo path and the real path are the same path.
  function loadDemo(n) {
    const d = DEMOS.find((x) => x.n === n)
    if (!d) return
    setChain(d.chain); setAsset(d.asset); setDepth(d.depth); setDirection(d.direction)
    setAddress(d.address); setTouched(false); setLoadedDemo(d)
  }

  // Shown while the form still holds the demo exactly as loaded: edit the
  // address or the direction and it is no longer that demo.
  const demoInForm = loadedDemo && loadedDemo.address === trimmed && loadedDemo.direction === direction
    && loadedDemo.depth === depth && loadedDemo.chain === chain ? loadedDemo : null
  const recording = demoInForm && recordings[Number(demoInForm.n)]

  function submit(event) {
    event.preventDefault()
    setTouched(true)
    if (valid) open(trimmed)
  }

  return (
    <div className="card">
      <div className="body">
        <p className="lede">Follow a reported wallet's money to the exchange it left through.</p>
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
          <div className="examples">
            <label className="toggle" title="With this on, the trace stops expanding after 1 minute 30 seconds and reports what it reached, marked truncated. Off, it runs until the depth, fan-out and size limits stop it -- which on a busy wallet at 4 hops can take several minutes.">
              <input type="checkbox" checked={capped} onChange={(e) => setCapped(e.target.checked)} />
              <span className="switch" aria-hidden="true" />
              <span>Stop after <span className="mono">1:30</span></span>
            </label>
            <span className="sep" />
            <label htmlFor="example">Load a verified example</label>
            <select id="example" value="" onChange={(e) => { loadDemo(e.target.value); e.target.value = '' }} disabled={backendDown}>
              <option value="">Choose one of the twelve traces in DEMO.md…</option>
              {DEMOS.map((d) => (
                <option key={d.n} value={d.n} title={d.hook}>
                  {d.n} · {d.title} · {{ tron: 'Tron', bsc: 'BNB Chain', polygon: 'Polygon', arbitrum: 'Arbitrum' }[d.chain] ?? 'Ethereum'} {d.asset} · {d.depth} hop{d.depth === 1 ? '' : 's'}{d.direction === 'incoming' ? ' · reverse' : ''}
                </option>
              ))}
            </select>
            {recording && (
              <Link className="recorded-link" to={`/demo/${Number(demoInForm.n)}`} title="The trace as DEMO.md describes it, recorded on that date. Opens instantly; nothing is re-traced.">
                or open it as recorded · <span className="mono">{recording.recorded_at.slice(0, 10)}</span>
              </Link>
            )}
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
  )
}
