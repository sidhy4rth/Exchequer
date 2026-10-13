import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchHealth, runTrace } from '../api'
import Mark from '../components/Mark'
import ThemeToggle from '../components/ThemeToggle'
import { signOut } from '../session'

// The citizen's side: someone who has just lost money to a crypto scam.
//
// What they need first is not analysis but the next step, so the page leads
// with it (call 1930 now, file at cybercrime.gov.in), then helps them write
// down everything a complaint needs while they still remember it, and turns
// that into a summary they can paste into the portal, read out on the phone
// or print. Optionally it follows the money from the address they paid, in
// plain words, so the complaint can name the exchange.
//
// The draft stays in this browser (localStorage) and is never sent to the
// server; only the optional trace is, as an ordinary trace of a public
// address.

const DRAFT_KEY = 'exchequer-citizen-draft'
const ADDRESS_RE = { evm: /^0x[0-9a-fA-F]{40}$/, tron: /^T[1-9A-HJ-NP-Za-km-z]{33}$/ }
const TX_RE = { evm: /^0x[0-9a-fA-F]{64}$/, tron: /^[0-9a-fA-F]{64}$/ }

const SCAM_TYPES = [
  ['investment', 'Investment or trading app / website promising returns'],
  ['task', 'Part-time job or "task" scheme (likes, reviews, ratings)'],
  ['romance', 'Someone I met online asked me to invest or send crypto'],
  ['support', 'Fake customer support, exchange or wallet helpdesk'],
  ['phishing', 'A link or app emptied my wallet (phishing / drainer)'],
  ['other', 'Something else'],
]

const EMPTY = {
  scamType: '', when: '', chain: 'ethereum', asset: '', amount: '', amountInr: '',
  scammerAddress: '', myAddress: '', txHashes: '', contact: '', story: '', name: '', phone: '', email: '', city: '',
}

function loadDraft() {
  try { return { ...EMPTY, ...JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}') } } catch { return EMPTY }
}

export default function Citizen() {
  const navigate = useNavigate()
  const [form, setForm] = useState(loadDraft)
  const [chains, setChains] = useState([])
  const [trace, setTrace] = useState(null) // { status, result, error, progress }
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    fetchHealth().then((h) => setChains(Object.values(h.chains ?? {}).filter((c) => c.ready))).catch(() => {})
  }, [])
  useEffect(() => {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(form)) } catch { /* private mode */ }
  }, [form])

  const chain = chains.find((c) => c.key === form.chain)
  const family = chain?.address_family ?? (form.chain === 'tron' ? 'tron' : 'evm')
  const assets = chain?.assets?.map((a) => a.symbol) ?? []
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

  const problems = useMemo(() => {
    const p = {}
    const addr = form.scammerAddress.trim()
    if (addr && !ADDRESS_RE[family].test(addr)) p.scammerAddress = family === 'tron' ? 'A Tron address starts with T and is 34 characters long.' : 'This should start with 0x followed by 40 letters and numbers.'
    const mine = form.myAddress.trim()
    if (mine && !ADDRESS_RE[family].test(mine)) p.myAddress = 'This does not look like an address on the chosen network.'
    const bad = form.txHashes.split(/[\s,]+/).filter(Boolean).filter((h) => !TX_RE[family].test(h))
    if (bad.length) p.txHashes = `${bad.length} of these do not look like transaction IDs on the chosen network.`
    return p
  }, [form, family])

  const canTrace = form.scammerAddress.trim() && !problems.scammerAddress && chain

  async function followTheMoney() {
    setTrace({ status: 'running', progress: null })
    try {
      const result = await runTrace(
        { address: form.scammerAddress.trim(), chain: form.chain, asset: form.asset || undefined, maxDepth: 4 },
        (snap) => setTrace((t) => ({ ...t, progress: snap.progress })),
      )
      setTrace({ status: 'done', result })
    } catch (e) {
      setTrace({ status: 'failed', error: e.message })
    }
  }

  const summary = useMemo(() => complaintText(form, chain, trace?.result), [form, chain, trace])

  async function copy() {
    try { await navigator.clipboard.writeText(summary); setCopied(true); setTimeout(() => setCopied(false), 2000) } catch { /* no clipboard */ }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([summary], { type: 'text/plain;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url; a.download = 'crypto-fraud-complaint.txt'; a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  function clearDraft() {
    setForm(EMPTY); setTrace(null)
    try { localStorage.removeItem(DRAFT_KEY) } catch { /* nothing to remove */ }
  }

  return (
    <div className="citizen">
      <header className="citizen-top">
        <span className="brand"><Mark size={20} /><span>Exchequer</span></span>
        <span className="citizen-actions">
          <ThemeToggle />
          <button className="quiet" onClick={() => { signOut(); navigate('/signin/citizen') }}>Sign out</button>
        </span>
      </header>
      <main className="citizen-main">
        <section className="citizen-urgent" aria-labelledby="urgent-h">
          <h1 id="urgent-h">Lost money to a crypto scam? Act in the next few hours.</h1>
          <ol>
            <li><strong>Call 1930</strong>, the national cybercrime helpline, now. The sooner it is reported, the better the chance funds can still be frozen.</li>
            <li><strong>File a complaint</strong> at <a href="https://cybercrime.gov.in" target="_blank" rel="noopener noreferrer">cybercrime.gov.in</a>. The form below writes the details down for you.</li>
            <li><strong>Stop paying.</strong> Requests for a "tax", "unlock fee" or "withdrawal charge" to get your money back are the same scam again.</li>
            <li><strong>Keep everything</strong>: chats, screenshots, the website or app link, and the transaction IDs.</li>
          </ol>
        </section>

        <form className="citizen-form" onSubmit={(e) => e.preventDefault()}>
          <fieldset>
            <legend>What happened</legend>
            <label>Type of scam
              <select value={form.scamType} onChange={set('scamType')}>
                <option value="">Choose…</option>
                {SCAM_TYPES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label>When did you send the money?
              <input type="date" value={form.when} onChange={set('when')} max={new Date().toISOString().slice(0, 10)} />
            </label>
            <label className="wide">In your own words
              <textarea rows={4} value={form.story} onChange={set('story')} placeholder="How it started, what you were promised, when you realised." />
            </label>
            <label className="wide">How they contacted you
              <input value={form.contact} onChange={set('contact')} placeholder="App or website, phone numbers, Telegram / WhatsApp / Instagram handles, links" />
            </label>
          </fieldset>

          <fieldset>
            <legend>The payment</legend>
            <label>Network
              <select value={form.chain} onChange={set('chain')}>
                {(chains.length ? chains : [{ key: 'ethereum', name: 'Ethereum' }]).map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
              </select>
            </label>
            <label>Currency
              <select value={form.asset} onChange={set('asset')}>
                <option value="">{assets[0] ? `${assets[0]} (native)` : 'Native'}</option>
                {assets.slice(1).map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            </label>
            <label>Amount sent (crypto)
              <input inputMode="decimal" value={form.amount} onChange={set('amount')} placeholder="e.g. 1,250 USDT" />
            </label>
            <label>Amount lost (₹, approx.)
              <input inputMode="decimal" value={form.amountInr} onChange={set('amountInr')} placeholder="e.g. 1,05,000" />
            </label>
            <label className="wide">The address you sent it to
              <input className="mono" value={form.scammerAddress} onChange={set('scammerAddress')} spellCheck={false}
                aria-invalid={Boolean(problems.scammerAddress)} aria-describedby="scammer-help"
                placeholder={family === 'tron' ? 'T…' : '0x…'} />
              <small id="scammer-help" className={problems.scammerAddress ? 'bad' : ''}>{problems.scammerAddress ?? 'Copy it from your wallet or exchange app\'s withdrawal history.'}</small>
            </label>
            <label className="wide">Your own wallet address (optional)
              <input className="mono" value={form.myAddress} onChange={set('myAddress')} spellCheck={false} aria-invalid={Boolean(problems.myAddress)} />
              {problems.myAddress && <small className="bad">{problems.myAddress}</small>}
            </label>
            <label className="wide">Transaction IDs (optional, one per line)
              <textarea rows={2} className="mono" value={form.txHashes} onChange={set('txHashes')} spellCheck={false} aria-invalid={Boolean(problems.txHashes)} />
              {problems.txHashes && <small className="bad">{problems.txHashes}</small>}
            </label>
          </fieldset>

          <fieldset>
            <legend>Your details (for the complaint; never sent anywhere by this page)</legend>
            <label>Name<input value={form.name} onChange={set('name')} autoComplete="name" /></label>
            <label>Phone<input value={form.phone} onChange={set('phone')} autoComplete="tel" inputMode="tel" /></label>
            <label>Email<input value={form.email} onChange={set('email')} autoComplete="email" inputMode="email" /></label>
            <label>City / district<input value={form.city} onChange={set('city')} autoComplete="address-level2" /></label>
          </fieldset>
        </form>

        <section className="card citizen-trace" aria-live="polite">
          <div className="head"><span className="micro">Where did the money go?</span><span className="note">optional · reads public blockchain records</span></div>
          <div className="body">
            {!trace && (
              <>
                <p>Exchequer can follow the money from the address you paid and tell you which exchange it reached. Exchanges can freeze funds and identify their customers when the police ask, so naming the exchange makes your complaint more useful.</p>
                <button className="primary" disabled={!canTrace} onClick={followTheMoney}>Follow the money</button>
                {!canTrace && <small className="note">Enter the address you sent the money to first.</small>}
              </>
            )}
            {trace?.status === 'running' && <p>Following the money… {trace.progress?.hop ? `step ${trace.progress.hop} of ${trace.progress.max_depth ?? 4}` : ''} This can take a minute.</p>}
            {trace?.status === 'failed' && <p className="error-line">{trace.error}</p>}
            {trace?.status === 'done' && <TracePlain result={trace.result} />}
          </div>
        </section>

        <section className="card citizen-summary">
          <div className="head"><span className="micro">Your complaint summary</span><span className="note">paste into cybercrime.gov.in, read out on 1930, or print</span></div>
          <div className="body">
            <pre className="mono">{summary}</pre>
            <div className="verify-actions">
              <button className="primary" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
              <button onClick={download}>Download .txt</button>
              <button onClick={() => window.print()}>Print</button>
              <button className="quiet" onClick={clearDraft}>Clear the form</button>
            </div>
            <p className="note">Saved in this browser only, so you can come back to it. Use “Clear the form” on a shared computer.</p>
          </div>
        </section>
      </main>
    </div>
  )
}

function TracePlain({ result }) {
  if (result.exchange) {
    return (
      <div className="plain-result">
        <p className="big">Your money reached <strong>{result.exchange}</strong>.</p>
        <p>Tell the police: the funds arrived at {result.exchange} at the address below{result.attribution_inferred ? ' (identified from how the wallet behaves, so the exchange must confirm it)' : ''}. Only the exchange can say whose account it is, and only when the police ask.</p>
        <p className="mono addr-line">{result.exchange_address}</p>
        {result.case_id && <p className="note">Reference for the police: Exchequer case {result.case_id}.</p>}
      </div>
    )
  }
  const flagged = (result.risk_matches ?? []).some((m) => m.category === 'mixer')
  return (
    <div className="plain-result">
      <p className="big">The money could not be followed to an exchange.</p>
      <p>{flagged ? 'It went through a mixer, which deliberately hides where money goes next. ' : ''}That is common and does not mean the case is hopeless: report it anyway, with the address and transaction IDs, so it can be linked with other complaints.</p>
      {result.case_id && <p className="note">Reference for the police: Exchequer case {result.case_id}.</p>}
    </div>
  )
}

export function complaintText(f, chain, result) {
  const scam = SCAM_TYPES.find(([k]) => k === f.scamType)?.[1]
  const lines = [
    'CRYPTOCURRENCY FRAUD — COMPLAINT SUMMARY',
    '',
    `Complainant      : ${f.name || '(name)'}${f.city ? `, ${f.city}` : ''}`,
    `Phone / email    : ${[f.phone, f.email].filter(Boolean).join(' / ') || '(phone, email)'}`,
    '',
    `Type of fraud    : ${scam || '(type)'}`,
    `Date of payment  : ${f.when || '(date)'}`,
    `Network          : ${chain?.name ?? f.chain}`,
    `Currency         : ${f.asset || chain?.assets?.[0]?.symbol || ''}`,
    `Amount sent      : ${f.amount || '(amount)'}`,
    `Loss (approx.)   : ${f.amountInr ? `Rs ${f.amountInr}` : '(rupees)'}`,
    `Paid to address  : ${f.scammerAddress.trim() || '(address)'}`,
  ]
  if (f.myAddress.trim()) lines.push(`From my wallet   : ${f.myAddress.trim()}`)
  const hashes = f.txHashes.split(/[\s,]+/).filter(Boolean)
  if (hashes.length) lines.push('Transaction IDs  :', ...hashes.map((h) => `  ${h}`))
  if (f.contact.trim()) lines.push('', 'How I was contacted:', `  ${f.contact.trim()}`)
  if (f.story.trim()) lines.push('', 'What happened:', ...f.story.trim().split('\n').map((l) => `  ${l}`))
  if (result) {
    lines.push('', 'Where the money went (Exchequer trace of public blockchain records):')
    if (result.exchange) {
      lines.push(`  Reached ${result.exchange} at ${result.exchange_address}${result.attribution_inferred ? ' (inferred deposit address; the exchange must confirm)' : ''}.`)
    } else {
      lines.push('  Not followed to an exchange.')
    }
    if (result.case_id) lines.push(`  Exchequer case reference: ${result.case_id}`)
  }
  lines.push('', 'I request that the funds be traced and frozen and the persons responsible identified.')
  return lines.join('\n')
}
