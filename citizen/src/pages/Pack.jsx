import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { NCRP_NEEDED, ncrpShape, refusal, sendComplaint } from '../api.js'
import { readDraft, writeDraft } from '../draft.js'
import { checkHash } from '../hash.js'
import { Icon, OfficialLinks, ReportSteps, usePageTitle } from '../parts.jsx'

// C5: a complaint pack the citizen fills in and saves as a PDF through the
// browser's print screen (styles.css lays it out on A4). The draft stays in
// this tab's sessionStorage, and screenshots are listed by file name only,
// never read. Only if the citizen asks, and agrees, are its text details sent
// to the cyber cell queue (POST /api/complaints): never the screenshots.
const TEXT = ['name', 'mobile', 'started', 'app', 'link', 'contacts', 'upi', 'story']
const PAY = ['hash', 'amount', 'token', 'network', 'paidAt', 'wallet']
const OTHER = 'Another network'
const NETWORKS = ['Tron (TRC20)', 'Ethereum (ERC20)', 'BNB Smart Chain (BEP20)', 'Polygon', 'Arbitrum', OTHER]

let lastId = 0
const strings = (keys, from) => Object.fromEntries(keys.map((k) => [k, typeof from?.[k] === 'string' ? from[k] : '']))
const payment = (from) => ({ ...strings(PAY, from), id: ++lastId })
// `sent` is the reference once this pack is sent (never the code), so it is not sent twice.
const empty = () => ({ ...strings(TEXT), payments: [payment()], files: [], sent: '' })
const emptyPayment = (p) => PAY.every((k) => !p[k].trim())
const blank = (form) => !form.sent && !form.files.length && TEXT.every((k) => !form[k].trim()) && form.payments.every(emptyPayment)

function load() {
  // Storage blocked, or a draft that does not read: start empty.
  const saved = readDraft()
  if (!Array.isArray(saved?.payments) || !saved.payments.length) return empty()
  const files = Array.isArray(saved.files) ? saved.files.filter((name) => typeof name === 'string') : []
  return { ...strings(TEXT, saved), payments: saved.payments.map(payment), files,
    sent: typeof saved.sent === 'string' ? saved.sent : '' }
}

/** What is sent: the text answers and the payments given, never the screenshots. */
const toSend = (form, ncrp) => ({ ncrp, ...strings(TEXT, form),
  payments: form.payments.filter((p) => !emptyPayment(p)).map((p) => strings(PAY, p)) })

const ELSEWHERE = ' On another network, choose "Another network".'
const HASH_PROBLEMS = {
  address: 'This is a wallet address, not a payment. Put it under "Wallet you paid", and the payment\'s hash here.',
  chars: 'A hash has only the digits 0 to 9 and the letters a to f. Copy just the long code from the payment.'
    + ELSEWHERE,
  length: ({ length }) => `This has ${length} characters, and a hash has 64 (not counting a 0x at the start).`
    + ELSEWHERE,
}

/** {field id: what is wrong} for the answers that cannot be right; every answer is optional. */
function problems(form) {
  const found = {}
  if (form.mobile.trim() && !/^(?:\+?91|0)?[6-9]\d{9}$/.test(form.mobile.replace(/[\s-]/g, ''))) {
    found.mobile = 'Give a 10-digit mobile number, or leave it empty.'
  }
  for (const p of form.payments) {
    // On another network a hash or wallet can have any shape: only a Tron or
    // 0x wallet in the hash is still caught.
    const elsewhere = p.network === OTHER
    const hash = checkHash(p.hash)
    if (hash.reason === 'address' || (!hash.ok && hash.reason !== 'empty' && !elsewhere)) {
      const problem = HASH_PROBLEMS[hash.reason]
      found[`p${p.id}-hash`] = typeof problem === 'function' ? problem(hash) : problem
    }
    const amount = p.amount.replace(/[,\s]/g, '')
    if (amount && !(/^(\d+\.?\d*|\.\d+)$/.test(amount) && Number(amount) > 0)) {
      found[`p${p.id}-amount`] = 'Write the amount as a number, such as 9890 or 9,890.50.'
    }
    if (elsewhere) continue
    const wallet = checkHash(p.wallet)
    if (wallet.ok) {
      found[`p${p.id}-wallet`] = 'This is a transaction hash, not a wallet address. Put it under "Transaction hash".'
    } else if (!['empty', 'address'].includes(wallet.reason)) {
      found[`p${p.id}-wallet`] = 'This does not look like a wallet address. A Tron one starts with T and has 34 '
        + `characters; others start with 0x and have 42.${ELSEWHERE}`
    }
  }
  return found
}

function Field({ id, label, optional, hint, error, as: Tag = 'input', wide, onChange, ...input }) {
  const described = [hint && `${id}-hint`, error && `${id}-err`].filter(Boolean).join(' ')
  return (
    <div className={wide ? 'field wide' : 'field'}>
      <label htmlFor={id}>{label}{optional && <span className="opt"> (optional)</span>}</label>
      <Tag id={id} onChange={(e) => onChange(e.target.value)} aria-describedby={described || undefined}
        aria-invalid={error ? true : undefined} {...input} />
      {hint && <p className="hint" id={`${id}-hint`}>{hint}</p>}
      {error && <p className="err" id={`${id}-err`}>{error}</p>}
    </div>
  )
}

const CODE = { spellCheck: false, autoCapitalize: 'off', autoCorrect: 'off', autoComplete: 'off', className: 'mono' }

function Rows({ rows }) {
  return (
    <dl>
      {rows.map(([term, value, mono]) => (
        <div key={term}><dt>{term}</dt><dd className={mono ? 'mono' : undefined}>{value.trim() || 'Not given'}</dd></div>
      ))}
    </dl>
  )
}

/** The pack as it prints: a preview beside the form on a laptop, hidden on a phone. */
function Paper({ form }) {
  const payments = form.payments.filter((p) => !emptyPayment(p))
  const today = new Date().toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' })
  return (
    <section className="paper" aria-labelledby="paper-title">
      <h2 id="paper-title">Complaint pack</h2>
      <p className="paper-note">Prepared by the complainant for their own complaint, on {today}. This is not
        an official document: no police or government office made or checked it.</p>
      <h3>The complainant</h3>
      <Rows rows={[['Name', form.name], ['Mobile', form.mobile]]} />
      <h3>Who contacted them</h3>
      <Rows rows={[['Started on', form.started], ['App or website', form.app], ['Link', form.link],
        ['Phone numbers and chat usernames', form.contacts], ['UPI IDs or bank accounts paid', form.upi],
        ['What happened', form.story]]} />
      <h3>Crypto payments</h3>
      {payments.length ? payments.map((p, i) => {
        const hash = checkHash(p.hash)
        return (
          <div className="paper-pay" key={p.id}>
            <h4>Payment {i + 1}</h4>
            <Rows rows={[['Transaction hash', hash.ok ? hash.hash : p.hash, true],
              ['Amount', `${p.amount.trim()} ${p.token.trim()}`], ['Network', p.network],
              ['Date and time', p.paidAt.replace('T', ' ')], ['Wallet paid', p.wallet, true]]} />
          </div>
        )
      }) : <p>None given.</p>}
      <h3>Screenshots, given as separate files</h3>
      {form.files.length ? <ul role="list">{form.files.map((name) => <li key={name}>{name}</li>)}</ul>
        : <p>None listed.</p>}
      <p className="paper-note">To report: the National Cyber Crime Helpline, 1930, or the National Cyber Crime
        Reporting Portal, cybercrime.gov.in.</p>
    </section>
  )
}

/** Prints the sent card alone (styles.css): Save as PDF never prints the code. */
const PRINT_CODE = 'print-code'
const codePrinted = () => document.documentElement.classList.remove(PRINT_CODE)
function printCode() {
  document.documentElement.classList.add(PRINT_CODE)
  window.addEventListener('afterprint', codePrinted, { once: true })
  window.print()
}

/** Send to the cyber cell queue, then the tracking code, shown this once. */
function Send({ form, ready, onSent }) {
  const [ncrp, setNcrp] = useState('')
  const [agreed, setAgreed] = useState(false)
  const [alert, setAlert] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(null)
  const [copied, setCopied] = useState('')
  const head = useRef(null)
  useEffect(() => { if (sent) head.current?.focus() }, [sent])
  useEffect(() => codePrinted, [])

  async function send(e) {
    e.preventDefault()
    const wrong = !ncrpShape(ncrp) ? ['ncrp', NCRP_NEEDED]
      : !agreed ? ['consent', 'Tick the box to agree to what is sent.'] : null
    if (wrong) document.getElementById(wrong[0])?.focus()
    const problem = wrong?.[1] || ready()
    setAlert(problem)
    if (problem) return
    setBusy(true)
    const res = await sendComplaint(toSend(form, ncrp.trim()))
    setBusy(false)
    if (!res.ok) return setAlert(refusal(res))
    setSent(res.data)
    onSent(String(res.data.reference ?? ''))
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(sent.tracking_code)
      setCopied('Copied.')
    } catch { setCopied('This browser could not copy it: write it down.') }
  }

  if (sent) {
    return (
      <section className="card send is-sent" aria-labelledby="sent-title">
        <h2 id="sent-title" ref={head} tabIndex={-1}>Sent. Write this code down now</h2>
        <p>Your complaint is in the cyber cell queue, as <strong className="mono">{sent.reference}</strong>.</p>
        <p className="code-name">Your tracking code</p>
        <p className="code mono">{sent.tracking_code}</p>
        <p className="code-warn">We cannot show it again, and we cannot send it to you. With your NCRP number, it
          opens your complaint under My case.</p>
        <div className="sent-actions">
          <button type="button" className="btn btn-line" onClick={copy}>Copy the code</button>
          <button type="button" className="btn btn-line" onClick={printCode}>Print the code</button>
        </div>
        <p className="status" role="status">{copied}</p>
        <Link className="more" to="/my-case">Open My case<Icon name="arrow" /></Link>
        <p className="warn"><Icon name="ban" />Never share this code with anyone who calls you, even someone who says
          they are police.</p>
      </section>)
  }
  if (form.sent) {
    return (
      <section className="card send" aria-labelledby="send-title">
        <h2 id="send-title">Sent to the cyber cell queue</h2>
        <p>This pack is in the queue as <strong className="mono">{form.sent}</strong>. Follow it under My case,
          with your NCRP number and tracking code.</p>
        <Link className="more" to="/my-case">Open My case<Icon name="arrow" /></Link>
        <p className="hint">To send a different complaint, clear this form first.</p>
      </section>)
  }
  return (
    <section className="card send" aria-labelledby="send-title">
      <h2 id="send-title">Send to the cyber cell queue</h2>
      <p className="hint">Already reported on 1930 or cybercrime.gov.in? Send this pack here too, so a cyber cell
        officer can read it and write back to you under My case.</p>
      <form className="send-form" onSubmit={send} noValidate>
        <div className="field">
          <label htmlFor="ncrp">NCRP acknowledgement number</label>
          <input id="ncrp" className="mono" value={ncrp} onChange={(e) => setNcrp(e.target.value)} autoComplete="off"
            autoCapitalize="characters" spellCheck={false} aria-describedby="ncrp-hint" />
          <p className="hint" id="ncrp-hint">The number you got from 1930 or cybercrime.gov.in. You sign in with it.</p>
        </div>
        <label className="consent">
          <input id="consent" type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
          <span>Send the text details in this pack, your answers and payments, to the cyber cell queue. Your
            screenshots are not sent: they stay on this device.</span>
        </label>
        {alert && <p className="err" role="alert">{alert}</p>}
        <button className="btn btn-go" type="submit" disabled={busy}>Send to the cyber cell queue<Icon name="arrow" />
        </button>
      </form>
      <p className="hint">Only officers who review complaints read it. Nothing here is public.</p>
    </section>
  )
}

export default function Pack() {
  usePageTitle('Your complaint pack')
  const [form, setForm] = useState(load)
  const [tried, setTried] = useState(false)
  const [note, setNote] = useState('')
  const focusNext = useRef(null)
  const found = tried ? problems(form) : {}

  useEffect(() => { writeDraft(blank(form) ? null : form) }, [form])
  useEffect(() => {
    if (focusNext.current) document.getElementById(focusNext.current)?.focus()
    focusNext.current = null
  })

  const change = (update) => { setForm(update); setNote('') }
  const set = (key) => (value) => change((f) => ({ ...f, [key]: value }))
  const setPay = (id, key) => (value) => change((f) => ({
    ...f, payments: f.payments.map((p) => (p.id === id ? { ...p, [key]: value } : p)) }))

  function addPayment() {
    const added = payment()
    focusNext.current = `p${added.id}-hash`
    change((f) => ({ ...f, payments: [...f.payments, added] }))
  }
  function removePayment(id) {
    focusNext.current = 'add-payment'
    change((f) => ({ ...f, payments: f.payments.filter((p) => p.id !== id) }))
  }
  function addFiles(e) {
    // The name only: the files themselves are never opened.
    const names = [...e.target.files].map((file) => file.name)
    e.target.value = ''
    change((f) => ({ ...f, files: [...new Set([...f.files, ...names])] }))
  }
  function removeFile(name) {
    focusNext.current = 'shots'
    change((f) => ({ ...f, files: f.files.filter((n) => n !== name) }))
  }
  /** '' when nothing is marked; otherwise what to check, with focus on the first. */
  function ready() {
    const wrong = Object.keys(problems(form))
    setTried(true)
    if (!wrong.length) return ''
    document.getElementById(wrong[0])?.focus()
    return wrong.length === 1 ? 'Check the answer marked in red first.'
      : `Check the ${wrong.length} answers marked in red first.`
  }
  function save() {
    const wrong = ready()
    setNote(wrong)
    if (wrong) return
    codePrinted()
    window.print()
  }
  function clear() {
    if (!window.confirm('Clear everything in this form?')) return
    setForm(empty())
    setTried(false)
    setNote('The form is cleared.')
  }

  return (
    <>
      <div className="page-head">
        <Link to="/report" className="back" aria-label="Back to find your payment"><Icon name="back" /></Link>
        <div><p className="eyebrow">Report</p><h1>Your complaint pack</h1></div>
      </div>
      <ReportSteps at={2} />
      <p className="lede">Fill in what you know, then save it as a PDF to give with your complaint. You can
        leave anything empty.</p>
      <div className="pack">
        <form className="pack-form" onSubmit={(e) => e.preventDefault()}>
          <section className="card">
            <h2>About you</h2>
            <div className="fields">
              <Field id="name" label="Your name" optional autoComplete="name" value={form.name}
                onChange={set('name')} />
              <Field id="mobile" label="Your mobile number" optional type="tel" inputMode="tel" autoComplete="tel"
                value={form.mobile} onChange={set('mobile')} error={found.mobile} />
            </div>
          </section>
          <section className="card">
            <h2>Who contacted you</h2>
            <div className="fields">
              <Field id="started" label="When it started" type="date" value={form.started} onChange={set('started')} />
              <Field id="app" label="App or website name" value={form.app} onChange={set('app')} />
              <Field id="link" label="Link to the app or website" inputMode="url" {...CODE}
                value={form.link} onChange={set('link')} wide />
              <Field id="contacts" as="textarea" rows={3} label="Phone numbers and chat usernames they used"
                hint="One per line: phone and WhatsApp numbers, Telegram usernames." value={form.contacts}
                onChange={set('contacts')} />
              <Field id="upi" as="textarea" rows={3} label="UPI IDs or bank accounts you paid"
                hint="If you also paid in rupees. One per line." value={form.upi} onChange={set('upi')} />
              <Field id="story" as="textarea" rows={4} label="What happened, in your words" wide
                hint="How they contacted you, what they promised, and when you paid." value={form.story}
                onChange={set('story')} />
            </div>
          </section>
          <section className="card">
            <h2>Crypto payments</h2>
            <p className="hint">One for each payment. Your wallet or exchange app shows these in the payment's
              details. <Link className="inline" to="/report">Where to find the hash</Link></p>
            {form.payments.map((p, i) => (
              <fieldset className="payment" key={p.id}>
                <legend>Payment {i + 1}</legend>
                <div className="fields">
                  <Field id={`p${p.id}-hash`} label="Transaction hash" wide {...CODE} value={p.hash}
                    onChange={setPay(p.id, 'hash')} error={found[`p${p.id}-hash`]} />
                  <Field id={`p${p.id}-amount`} label="Amount" inputMode="decimal" value={p.amount}
                    onChange={setPay(p.id, 'amount')} error={found[`p${p.id}-amount`]} />
                  <Field id={`p${p.id}-token`} label="Token" placeholder="USDT" autoCapitalize="characters"
                    value={p.token} onChange={setPay(p.id, 'token')} />
                  <Field id={`p${p.id}-network`} as="select" label="Network" value={p.network}
                    onChange={setPay(p.id, 'network')}>
                    <option value="">Not sure</option>
                    {NETWORKS.map((name) => <option key={name}>{name}</option>)}
                  </Field>
                  <Field id={`p${p.id}-paidAt`} label="Date and time" type="datetime-local" value={p.paidAt}
                    onChange={setPay(p.id, 'paidAt')} />
                  <Field id={`p${p.id}-wallet`} label="Wallet you paid" wide {...CODE} value={p.wallet}
                    onChange={setPay(p.id, 'wallet')} error={found[`p${p.id}-wallet`]} />
                </div>
                {form.payments.length > 1 && (
                  <button type="button" className="btn btn-line small" onClick={() => removePayment(p.id)}>
                    Remove <span className="sr-only">payment {i + 1}</span></button>)}
              </fieldset>
            ))}
            <button type="button" id="add-payment" className="btn btn-line" onClick={addPayment}>
              <Icon name="plus" />Add another payment</button>
          </section>
          <section className="card">
            <h2>Screenshots</h2>
            <label className="drop">
              <input id="shots" type="file" multiple accept="image/*,application/pdf" onChange={addFiles} />
              <Icon name="image" size={18} />Add screenshots of the chats and the app
            </label>
            <p className="hint">Only their file names go in the pack. The files stay on your device: give them
              with the pack.</p>
            {form.files.length > 0 && (
              <ul className="shots" role="list" aria-label="Your screenshots">
                {form.files.map((name) => (
                  <li key={name}><span>{name}</span>
                    <button type="button" className="btn btn-line small" onClick={() => removeFile(name)}>
                      Remove <span className="sr-only">{name}</span></button></li>
                ))}
              </ul>)}
          </section>
        </form>
        <Paper form={form} />
        <div className="pack-actions">
          <button type="button" className="btn btn-go" onClick={save}><Icon name="save" />Save as PDF</button>
          <p className="hint">Your print screen opens: choose Save as PDF (on an iPhone, tap Share, then Save to
            Files). If nothing opens, open this page in Chrome or Safari.</p>
          <p className="status" role="status">{note}</p>
          <p className="hint">Nothing you type here is sent unless you choose Send to the cyber cell queue. It is
            kept only in this browser tab. On a shared device, press Clear this form when you are done.</p>
          <button type="button" className="btn btn-line" onClick={clear}>Clear this form</button>
        </div>
        <Send form={form} ready={ready} onSent={(ref) => change((f) => ({ ...f, sent: ref }))} />
        <section className="card pack-next" aria-labelledby="next-title">
          <h2 id="next-title">Then report it</h2>
          <ol className="next-steps" role="list">
            <li>Save this pack as a PDF.</li>
            <li>Upload it with your screenshots at cybercrime.gov.in, or take both to your nearest cyber cell.</li>
            <li>Call 1930, the National Cyber Crime Helpline, if you have not yet. The first hours matter most.</li>
          </ol>
          <OfficialLinks />
        </section>
      </div>
    </>
  )
}
