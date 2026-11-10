import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { NCRP_NEEDED, amountText, istTime, myCase, ncrpShape, refusal, sendMessage, signIn, signOut } from '../api.js'
import { Icon, usePageTitle } from '../parts.jsx'

// C6 and C7: sign in with the NCRP number and the tracking code shown once
// when the complaint was sent (no SMS, no e-mail), then the citizen's own
// complaint: a coarse status, the messages, and what they sent. Only fields
// named here are shown: anything else a server sends is never rendered.
const STEPS = [
  ['received', 'Received', (n) => (n ? `your complaint and ${n} payment${n > 1 ? 's' : ''}` : 'your complaint')],
  ['with_cell', 'With a cyber cell', () => 'an officer has your complaint'],
  ['investigating', 'Under investigation', () => 'an officer is following your payment'],
  ['closed', 'Closed', () => 'you will be told the outcome here'],
]
const ANSWERS = [['name', 'Your name'], ['mobile', 'Your mobile'], ['started', 'When it started'],
  ['app', 'App or website'], ['link', 'Link'], ['contacts', 'Phone numbers and chat usernames'],
  ['upi', 'UPI IDs or bank accounts'], ['story', 'What happened']]
const NEVER_SHARE = 'Never share this code with anyone who calls you, even someone who says they are police.'

/** The h1 to focus when this view replaced another, whose focused button went with it. */
function useHeading(focus) {
  const head = useRef(null)
  useEffect(() => { if (focus) head.current?.focus() }, [focus])
  return head
}

function SignIn({ given, focus, onIn }) {
  usePageTitle('Follow your complaint')
  const head = useHeading(focus)
  // Filled in after the form appears, so a screen reader announces it.
  const [status, setStatus] = useState('')
  useEffect(() => setStatus(given.status ?? ''), [given.status])
  const [ncrp, setNcrp] = useState('')
  const [code, setCode] = useState('')
  const [alert, setAlert] = useState(given.alert ?? '')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    const missing = !ncrpShape(ncrp) ? ['ncrp', NCRP_NEEDED]
      : !code.trim() ? ['code', 'Give the tracking code you were shown when you sent your complaint.'] : null
    if (missing) {
      setAlert(missing[1])
      document.getElementById(missing[0])?.focus()
      return
    }
    setBusy(true)
    setAlert('')
    const res = await signIn(ncrp.trim(), code.trim())
    setBusy(false)
    if (res.ok) return onIn()
    setCode('')
    setAlert(refusal(res))
  }

  return (
    <div className="signin">
      <div className="signin-intro">
        <h1 ref={head} tabIndex={-1}>Follow your complaint</h1>
        <p className="lede">Sign in with the NCRP acknowledgement number you got from 1930 or cybercrime.gov.in, and
          the tracking code shown once when you sent your complaint pack here.</p>
        <ul className="ticks" role="list">
          {['Where your complaint is', 'Messages from the cyber cell', 'What you gave us'].map((t) => (
            <li key={t}><Icon name="check" />{t}</li>))}
        </ul>
        <p className="hint">Not sent one yet? <Link className="inline" to="/report/pack">Make your complaint pack</Link></p>
      </div>
      <form className="card signin-form" aria-label="Sign in" onSubmit={submit} noValidate>
        <div className="field">
          <label htmlFor="ncrp">NCRP acknowledgement number</label>
          <input id="ncrp" className="mono" value={ncrp} onChange={(e) => setNcrp(e.target.value)} autoComplete="off"
            autoCapitalize="characters" spellCheck={false} />
        </div>
        <div className="field">
          <label htmlFor="code">Tracking code</label>
          <input id="code" className="mono" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off"
            autoCapitalize="characters" spellCheck={false} aria-describedby="code-hint" />
          <p className="hint" id="code-hint">The 12 letters and digits shown once when you sent your complaint here.
            Lost it? We cannot show it again or send it to you: follow your complaint on 1930 instead.</p>
        </div>
        {alert && <p className="err" role="alert">{alert}</p>}
        <p className="status" role="status">{status}</p>
        <button className="btn btn-go" type="submit" disabled={busy}>Open my complaint</button>
        <p className="warn"><Icon name="ban" />{NEVER_SHARE}</p>
      </form>
    </div>
  )
}

function Reply({ onSent, onOut }) {
  const [text, setText] = useState('')
  const [alert, setAlert] = useState('')
  const [busy, setBusy] = useState(false)
  async function send(e) {
    e.preventDefault()
    if (!text.trim()) return setAlert('Write a message first.')
    setBusy(true)
    setAlert('')
    const res = await sendMessage(text)
    setBusy(false)
    if (res.status === 401) return onOut()
    if (!res.ok) return setAlert(refusal(res))
    setText('')
    onSent()
  }
  return (
    <form className="reply" onSubmit={send} noValidate>
      <label htmlFor="reply">Write to the cyber cell</label>
      <textarea id="reply" rows={3} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)}
        aria-describedby="reply-hint" />
      <p className="hint" id="reply-hint">Screenshots stay on your device: say what they show, and give them to the
        officer when asked.</p>
      {alert && <p className="err" role="alert">{alert}</p>}
      <button className="btn btn-go" type="submit" disabled={busy}>Send</button>
    </form>
  )
}

function Case({ data, focus, reload, onOut, onSignOut }) {
  usePageTitle('My complaint')
  const head = useHeading(focus)
  const payments = Array.isArray(data.payments) ? data.payments : []
  const messages = Array.isArray(data.messages) ? data.messages : []
  const sent = data.sent ?? {}
  const now = Math.max(0, STEPS.findIndex(([key]) => key === data.status?.key))
  const closed = STEPS[now][0] === 'closed'
  return (
    <div className="case">
      <div className="case-head">
        <div><p className="eyebrow">Reference <span className="mono">{data.reference}</span></p><h1 ref={head} tabIndex={-1}>My complaint</h1></div>
        <button type="button" className="btn btn-line small" onClick={onSignOut}>Sign out</button>
      </div>
      <ol className="card progress" role="list" aria-label="Where your complaint is">
        {STEPS.map(([key, title, sub], i) => {
          const done = i < now || closed
          return (
            <li key={key} className={done ? 'done' : i === now ? 'now' : undefined}
              aria-current={i === now ? 'step' : undefined}>
              <span className="dot" aria-hidden="true">{done && <Icon name="check" size={12} />}</span>
              <span className="sr-only">{done ? 'Done: ' : i === now ? 'Now: ' : 'Not yet: '}</span>
              <span className="step-title">{title}</span><span className="step-sub">{sub(payments.length)}</span>
            </li>)
        })}
      </ol>
      <section className="card messages" aria-labelledby="messages-title">
        <h2 id="messages-title">Messages</h2>
        {messages.length ? (
          <ol className="thread" role="list" aria-labelledby="messages-title">
            {messages.map((m, i) => {
              const mine = m.from === 'You'
              return (
                <li key={i} className={mine ? 'msg mine' : 'msg'}>
                  <p className="msg-head">{mine ? 'You' : 'Cyber cell'} · {istTime(m.at)}</p>
                  <p className="msg-body">{String(m.body ?? '')}</p>
                </li>)
            })}
          </ol>) : <p className="hint">No messages yet. When the cyber cell writes to you, it shows here.</p>}
        <Reply onSent={reload} onOut={onOut} />
      </section>
      <section className="card gave" aria-labelledby="gave-title">
        <h2 id="gave-title">What you gave us</h2>
        <p className="hint">Sent on {istTime(data.sent_at)}</p>
        <h3>Payments</h3>
        {payments.length ? (
          <ul className="gave-pays" role="list">
            {payments.map((p, i) => (
              <li key={i}>
                <strong>{`${amountText(p.amount)} ${p.token ?? ''}`.trim() || `Payment ${i + 1}`}</strong>
                {p.network && <span className="hint">{p.network}</span>}
                {p.hash && <code className="hash">{p.hash}</code>}
                {p.wallet && <span className="hint">To <code>{p.wallet}</code></span>}
              </li>))}
          </ul>) : <p className="hint">None given.</p>}
        <h3>Your answers</h3>
        <dl className="answers">
          {ANSWERS.filter(([key]) => String(sent[key] ?? '').trim()).map(([key, label]) => (
            <div key={key}><dt>{label}</dt><dd>{String(sent[key])}</dd></div>))}
        </dl>
        <p className="hint">Screenshots: kept on your device, never sent.</p>
      </section>
      <p className="warn case-warn"><Icon name="ban" />Updates come only here. Anyone who calls offering to get your
        money back for a fee is a scammer.</p>
    </div>
  )
}

export default function MyCase() {
  const [state, setState] = useState({ view: 'loading' })
  const alive = useRef(true)
  useEffect(() => () => { alive.current = false }, [])
  const show = (next) => alive.current && setState(next)

  // focus: this follows something the citizen did, not the page opening.
  const load = useCallback(async (focus = false) => {
    const res = await myCase()
    if (!alive.current) return
    if (res.ok) setState({ view: 'case', data: res.data, focus })
    else if (res.status === 401) setState({ view: 'signin', given: {}, focus })
    else setState({ view: 'error', error: refusal(res) })
  }, [])
  useEffect(() => { alive.current = true; load() }, [load])

  async function out() {
    const res = await signOut()
    if (res.ok) show({ view: 'signin', given: { status: 'You are signed out.' }, focus: true })
    else show({ ...state, view: 'error', error: refusal(res) })
  }

  if (state.view === 'signin') return <SignIn given={state.given} focus={state.focus} onIn={() => load(true)} />
  if (state.view === 'case') {
    return <Case data={state.data} focus={state.focus} reload={() => load()} onSignOut={out}
      onOut={() => show({ view: 'signin', given: { alert: 'Please sign in again.' }, focus: true })} />
  }
  if (state.view === 'error') {
    return (
      <div className="soon">
        <h1>My complaint</h1>
        <p className="err" role="alert">{state.error}</p>
        <button type="button" className="btn btn-line" onClick={() => { setState({ view: 'loading' }); load(true) }}>
          Try again</button>
      </div>)
  }
  return <p className="status" role="status">Opening your complaint…</p>
}
