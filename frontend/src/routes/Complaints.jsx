import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { claimComplaint, fetchChains, fetchComplaint, fetchComplaints, linkComplaintCase, sendComplaintMessage, setComplaintStatus } from '../api'
import { useMedia } from '../phone'
import { useAccount } from '../session'
import { plain } from '../text'
import './Complaints.css'

// The Complaints page (/complaints): the officers' review queue of what
// citizens sent from their own site (backend/app/routes/complaints.py), and
// one complaint at /complaints/<reference>. Data flows one way: the only
// thing that goes back to the citizen is a message written here. Whether
// the wallet paid is in other complaints is for officers alone. A trace
// starts only when the officer presses for it on the New trace page. A
// complaint belongs to no unit until a signed-in officer claims it for
// theirs, and they claim it before acting on it; a demo user's queue is as it was.

export const STATUS = { received: 'Received', with_cell: 'With a cyber cell', investigating: 'Under investigation', closed: 'Closed' }
// The citizen site's networks (citizen/api/_lib/complaint.py), each with the chain it is traced on.
const CHAIN = { 'Tron (TRC20)': 'tron', 'Ethereum (ERC20)': 'ethereum', 'BNB Smart Chain (BEP20)': 'bsc', Polygon: 'polygon', Arbitrum: 'arbitrum' }
const FIELDS = [['name', 'Name'], ['mobile', 'Mobile'], ['started', 'When it started'], ['app', 'App or website'], ['link', 'Link they gave'],
  ['contacts', 'Phone numbers and chat usernames used'], ['upi', 'UPI IDs or bank accounts paid'], ['story', 'What happened']]
const CARDS = '(max-width: 959px)'
// The NCRP number as New trace and the trace pipeline take it; the citizen
// site takes 8 to 20 letters and digits.
const TRACE_NCRP = /^[0-9]{10,20}$/

const DAY = { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' }
const IST = new Intl.DateTimeFormat('en-GB', DAY)
const IST_TIME = new Intl.DateTimeFormat('en-GB', { ...DAY, hour: '2-digit', minute: '2-digit', hour12: false })
const AMOUNT = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 8 })
/** The store keeps UTC; an officer reads the time in India. */
function inIst(at, format = IST) {
  const text = String(at ?? '')
  const when = new Date(/(Z|[+-]\d\d:?\d\d)$/i.test(text) ? text : `${text}Z`)
  return Number.isNaN(when.getTime()) ? '—' : format.format(when)
}
const money = (amount, token) => [amount && !Number.isNaN(Number(amount)) ? AMOUNT.format(Number(amount)) : plain(amount), plain(token)].filter(Boolean).join(' ')
const total = (totals) => (totals.length ? totals.map((t) => money(t.amount, t.token)).join(' + ') : '—')
/** The citizen's own words: every line read as plain() reads a name, the lines kept. */
const lines = (text) => String(text ?? '').split('\n').map(plain).join('\n')
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`
const unitOf = (c) => (c.unit ? plain(c.unit.name) : 'Unclaimed')
const CLAIM_FIRST = 'Claim this complaint for your unit to change its status, link a case or reply.'

const Flags = ({ c }) => (c.in_other_complaints || c.in_stored_case) && (
  <span className="cq-flags">
    {c.in_other_complaints && <span className="pill red">Wallet also in other complaints</span>}
    {c.in_stored_case && <span className="pill amber">Wallet in a stored case</span>}
  </span>
)

function Table({ rows }) {
  const navigate = useNavigate()
  return (
    <table className="cases-list" aria-label="Complaints">
      <thead>
        <tr><th>Reference</th><th>Received (IST)</th><th>NCRP</th><th className="end">Payments</th><th className="end">Total</th><th>Status</th><th>Unit</th></tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.reference} className="row" onClick={(e) => { if (!e.target.closest('a')) navigate(`/complaints/${c.reference}`) }}>
            <td className="cases-wallet"><Link to={`/complaints/${c.reference}`} className="mono">{c.reference}</Link><Flags c={c} /></td>
            <td className="soft">{inIst(c.received_at)}</td>
            <td className="mono soft">{c.ncrp}</td>
            <td className="num">{c.payments}</td>
            <td className="num">{total(c.totals)}</td>
            <td>{STATUS[c.status] ?? plain(c.status)}</td>
            <td className="soft">{unitOf(c)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Cards({ rows }) {
  return (
    <ul className="recent-cases cases-cards" aria-label="Complaints">
      {rows.map((c) => (
        <li key={c.reference}>
          <Link to={`/complaints/${c.reference}`}>
            <span className="mono recent-address">{c.reference}</span>
            <span className="recent-meta">{[inIst(c.received_at), `NCRP ${c.ncrp}`, plural(c.payments, 'payment'), unitOf(c)].join(' · ')}<Flags c={c} /></span>
            <span className="recent-reached">{total(c.totals)}</span>
            <span className="recent-band">{STATUS[c.status] ?? plain(c.status)}</span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

function Queue() {
  // undefined while asking; null when the queue cannot be read.
  const [rows, setRows] = useState(undefined)
  const [total, setTotal] = useState(0)
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')
  const [more, setMore] = useState(false)
  const cards = useMedia(CARDS)
  // Counts the lists asked for, so an older page asked for under one filter
  // is dropped if it comes back after another filter was picked.
  const asked = useRef(0)
  useEffect(() => {
    let live = true
    asked.current += 1
    setRows(undefined); setError(''); setMore(false)
    fetchComplaints(status).then((d) => { if (live) { setRows(d.complaints ?? []); setTotal(d.total ?? 0) } })
      .catch((e) => { if (live) { setError(e.message); setRows(null) } })
    return () => { live = false }
  }, [status])
  // The next page starts where this one stops; a complaint that arrived in
  // between pushes one row down again, so a reference already listed is skipped.
  function older() {
    const mine = asked.current
    const still = () => asked.current === mine
    setMore(true)
    fetchComplaints(status, rows.length).then((d) => {
      if (!still()) return
      setTotal(d.total ?? 0)
      setRows((now) => now && [...now, ...(d.complaints ?? []).filter((c) => !now.some((r) => r.reference === c.reference))])
    }).catch((e) => { if (still()) setError(e.message) }).finally(() => { if (still()) setMore(false) })
  }

  return (
    <div className="work console work-complaints">
      <header className="work-head">
        <p className="note">Sent by citizens from their own site · only the messages you send go back</p>
        <h1>Complaints</h1>
      </header>
      <div className="cases-filters">
        <div role="group" aria-label="Filter by status">
          {[[null, 'All'], ...Object.entries(STATUS)].map(([key, label]) => (
            <button key={label} type="button" aria-pressed={status === key} onClick={() => setStatus(key)}>{label}</button>
          ))}
        </div>
      </div>
      {rows === undefined && <p className="note">Reading the queue…</p>}
      {rows === null && <p className="note banner">{error}</p>}
      {rows?.length === 0 && <p className="note">{status ? `No complaint is marked ${STATUS[status].toLowerCase()}.` : 'No complaints yet.'}</p>}
      {rows?.length > 0 && <div className="card glass cases-card">{cards ? <Cards rows={rows} /> : <Table rows={rows} />}</div>}
      {rows?.length > 0 && rows.length < total && (
        <div className="cq-more">
          <p className="note">{`Showing the newest ${rows.length} of ${total} complaints.`}</p>
          <button type="button" disabled={more} onClick={older}>Show older complaints</button>
        </div>
      )}
      {rows && error && <p className="note banner" role="alert">{error}</p>}
    </div>
  )
}

function Ncrp({ value }) {
  const [shown, setShown] = useState(false)
  return (
    <span className="cq-ncrp">NCRP <span className="mono">{shown ? value : `••••${value.slice(-4)}`}</span>
      <button type="button" className="quiet" aria-pressed={shown} aria-label="Show the NCRP number" onClick={() => setShown((v) => !v)}>Show</button>
    </span>
  )
}

/** Whether this site traces `chain` (GET /chains): null while asking. */
const traces = (health, chain) => (health ? Boolean(health.chains?.[chain]?.ready) : null)

function Payment({ p, n, ncrp, health }) {
  const navigate = useNavigate()
  const chain = CHAIN[p.network]
  const on = traces(health, chain)
  // An NCRP number New trace would refuse is left out, not filled in to block the trace.
  const ack = TRACE_NCRP.test(ncrp) ? ncrp : ''
  const bare = p.hash.replace(/^0x/i, '')
  function trace() {
    // The hash is public chain data and goes in the link, as the trace form
    // sends it; the wallet and the NCRP number travel in this tab's state.
    const q = new URLSearchParams({ ...(bare ? { pay: chain === 'tron' ? bare : `0x${bare}` } : {}), chain, ...(p.token ? { asset: p.token.toUpperCase() } : {}) })
    navigate(`/trace/new?${q}`, { state: { prefill: { address: p.wallet, ncrpAck: ack } } })
  }
  return (
    <li className="cq-payment">
      <p className="cq-amount" id={`cq-pay-${n}`}>{money(p.amount, p.token) || 'Amount not given'}<span className="note"> · {plain(p.network) || 'network not given'}{p.paid_at && ` · paid ${plain(p.paid_at.replace('T', ' '))}`}</span></p>
      <dl>
        <div><dt>Wallet paid</dt><dd className="mono">{plain(p.wallet) || '—'}</dd></div>
        <div><dt>Transaction hash</dt><dd className="mono">{plain(p.hash) || '—'}</dd></div>
      </dl>
      {!chain && <p className="note">Exchequer does not trace this network.</p>}
      {chain && on === false && <p className="note">{`Exchequer does not trace ${plain(p.network)} on this site.`}</p>}
      {chain && on && !p.wallet && <p className="note">No wallet was given, so there is nothing to trace from.</p>}
      {chain && on && p.wallet && <>
        <button type="button" className="primary" aria-describedby={`cq-pay-${n}`} onClick={trace}>Start a trace from this payment</button>
        {!ack && <p className="note">This complaint's NCRP number is not the 10 to 20 digits New trace takes, so New trace opens without the NCRP number.</p>}
      </>}
    </li>
  )
}

/** Which unit has the complaint; a signed-in officer claims an unclaimed
 * one for theirs, and the keyboard stays on what the claim said. */
function Claim({ c, officer, onClaimed }) {
  const [said, setSaid] = useState('')
  const [busy, setBusy] = useState(false)
  const line = useRef(null)
  async function claim() {
    setBusy(true)
    try {
      const { unit } = await claimComplaint(c.reference)
      onClaimed(unit)
      setSaid(`Claimed for ${plain(unit.name)}.`)
    } catch (e) { setSaid(e.message) } finally { setBusy(false) }
    line.current?.focus()
  }
  return (
    <section className="card glass cq-card" aria-labelledby="cq-unit">
      <h2 id="cq-unit">Unit</h2>
      {c.unit ? <p>{`Claimed by ${plain(c.unit.name)}.`}</p> : <p className="note">{officer
        ? 'No unit has claimed this complaint yet.'
        : 'No unit has claimed this complaint yet. Officers claim one for their unit once signed in.'}</p>}
      {!c.unit && officer && <button type="button" className="primary cq-claim" disabled={busy} onClick={claim}>Claim for my unit</button>}
      <p role="status" className="note cq-said" ref={line} tabIndex={-1}>{said}</p>
    </section>
  )
}

function Handling({ c, held }) {
  const [status, setStatus] = useState(c.status)
  const [caseId, setCaseId] = useState(c.case_id)
  const [caseText, setCaseText] = useState('')
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState('')
  async function run(event, action) {
    event.preventDefault()
    setBusy(true)
    try { setSaid(await action()) } catch (e) { setSaid(e.message) } finally { setBusy(false) }
  }
  const save = (e) => run(e, async () => `Status saved: ${STATUS[(await setComplaintStatus(c.reference, status)).status]}.`)
  const link = (e) => run(e, async () => {
    const linked = await linkComplaintCase(c.reference, caseText.trim())
    setCaseId(linked.case_id); setCaseText('')
    return 'Case linked.'
  })
  return (
    <section className="card glass cq-card" aria-labelledby="cq-handling">
      <h2 id="cq-handling">Status and case</h2>
      {held ? <p className="note">{CLAIM_FIRST}</p> : <>
      <form className="cq-row" onSubmit={save}>
        <label htmlFor="cq-status">Status</label>
        <select id="cq-status" value={status} onChange={(e) => setStatus(e.target.value)}>
          {Object.entries(STATUS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <button type="submit" disabled={busy}>Save status</button>
      </form>
      <p className="note">The citizen sees this status, and nothing else about the work.</p>
      {caseId && <p><Link to={`/case/${encodeURIComponent(caseId)}`}>{`Open case ${plain(caseId)}`}</Link></p>}
      <form className="cq-row" onSubmit={link}>
        <label htmlFor="cq-case">Stored case ID</label>
        <input id="cq-case" className="mono" value={caseText} onChange={(e) => setCaseText(e.target.value)} spellCheck={false} autoComplete="off" maxLength={36} />
        <button type="submit" disabled={busy || !caseText.trim()}>Link case</button>
      </form>
      </>}
      <p role="status" className="note">{said}</p>
    </section>
  )
}

function Thread({ reference, initial, held }) {
  const [messages, setMessages] = useState(initial)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function send(event) {
    event.preventDefault()
    setBusy(true); setError('')
    try {
      const sent = await sendComplaintMessage(reference, text)
      setMessages((all) => [...all, sent]); setText('')
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return (
    <section className="card glass cq-card cq-thread" aria-labelledby="cq-messages">
      <h2 id="cq-messages">Messages</h2>
      {messages.length > 0
        ? <ol className="cq-messages">{messages.map((m, i) => (
            <li key={i} className={m.from === 'officer' ? 'officer' : ''}>
              <p className="note">{m.from === 'officer' ? 'Cyber cell (sent)' : 'Citizen'} · {inIst(m.at, IST_TIME)} IST</p>
              <p className="cq-body">{lines(m.body)}</p>
            </li>))}</ol>
        : <p className="note">No messages yet.</p>}
      {held ? <p className="note">{CLAIM_FIRST}</p> : <form onSubmit={send}>
        <label htmlFor="cq-reply">Message to the citizen</label>
        <p id="cq-reply-note" className="note">The citizen sees only what you write here. Never name where the money went, an exchange, other complaints or what a case found.</p>
        <textarea id="cq-reply" rows={4} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} aria-describedby="cq-reply-note" />
        {error && <p className="note banner" role="alert">{error}</p>}
        <button type="submit" className="primary" disabled={busy || !text.trim()}>Send to the citizen</button>
      </form>}
    </section>
  )
}

function Complaint({ reference }) {
  const { officer } = useAccount()
  const [c, setC] = useState(undefined)
  const [error, setError] = useState('')
  const [health, setHealth] = useState(null)
  useEffect(() => {
    fetchComplaint(reference).then(setC).catch((e) => { setError(e.message); setC(null) })
  }, [reference])
  // Unreachable reads as nothing traced: no button that would trace on the wrong chain.
  useEffect(() => { fetchChains().then(setHealth).catch(() => setHealth({ chains: {} })) }, [])
  if (!c) return <div className="work console"><p className={`note${c === null ? ' banner' : ''}`}>{c === null ? error : 'Opening the complaint…'}</p></div>
  const sent = FIELDS.filter(([key]) => c.details?.[key])
  return (
    <div className="work console work-complaint">
      <header className="work-head">
        <p className="note">Complaint received {inIst(c.received_at, IST_TIME)} IST</p>
        <h1 className="mono">{c.reference}</h1>
        <p className="cq-flags"><Ncrp value={c.ncrp} /><Flags c={c} /></p>
      </header>
      <div className="cq-grid">
        <Claim c={c} officer={officer} onClaimed={(unit) => setC((now) => ({ ...now, unit }))} />
        <section className="card glass cq-card" aria-labelledby="cq-sent">
          <h2 id="cq-sent">What the citizen wrote</h2>
          {sent.length ? <dl>{sent.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{lines(c.details[key])}</dd></div>)}</dl>
            : <p className="note">Only the payments were sent.</p>}
        </section>
        <section className="card glass cq-card" aria-labelledby="cq-payments">
          <h2 id="cq-payments">{`Payments · ${c.payments.length}`}</h2>
          {c.payments.length ? <ol className="cq-payments">{c.payments.map((p, i) => <Payment key={i} p={p} n={i} ncrp={c.ncrp} health={health} />)}</ol>
            : <p className="note">No payment was sent with this complaint.</p>}
        </section>
        <Handling c={c} held={Boolean(officer) && !c.unit} />
        <Thread reference={c.reference} initial={c.messages} held={Boolean(officer) && !c.unit} />
      </div>
    </div>
  )
}

export default function Complaints() {
  const { reference } = useParams()
  return reference ? <Complaint key={reference} reference={reference} /> : <Queue />
}
