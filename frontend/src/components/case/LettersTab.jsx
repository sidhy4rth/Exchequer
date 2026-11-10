import { memo, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchCaseRequests, fetchLetter, fetchLetters, fetchRecordedLetter, fetchRecordedLetters, logRequest, signOffRequest, updateRequest } from '../../api'
import { plain } from '../../text'
import RequestsPanel from '../RequestsPanel'
import WatchPanel from '../WatchPanel'
import { ist } from './format'
import { addressOf, assetOf, blanks, checks, kindOf, lines, recipientOf } from './letterChecks'
import './Letters.css'

const Tick = () => (
  <span className="lt-tick" aria-hidden="true">
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2.5 6.2l2.4 2.4 4.6-4.8" /></svg>
  </span>
)

/** Print the letter's sheet and nothing else: the browser's print dialog
 * saves it as a PDF. Letters.css hides the rest while html has print-letter. */
function printSheet() {
  const root = document.documentElement
  const done = () => { root.classList.remove('print-letter'); window.removeEventListener('afterprint', done) }
  root.classList.add('print-letter')
  window.addEventListener('afterprint', done)
  window.print()
}

const FALLBACK = { 'exchange-freeze': 'exchange', 'instant-freeze': 'instant' } // a case that lists no freeze letter opens the information letter

/** The case's Letters tab: the drafts the backend offers for it, one at a
 * time on a paper sheet, then the freeze-request log and the watches. A
 * recorded example (`recorded` is its number) shows its drafts, but only a
 * stored case can log one as sent. A Flow card can ask for one letter
 * (`pick`, its `to`) or one more wallet to watch (`watch`). */
function LettersTab({ result, recorded, pick: asked = null, watch = null }) {
  const caseId = result.case_id
  const source = caseId ? { list: () => fetchLetters(caseId), one: (to) => fetchLetter(caseId, to) }
    : recorded ? { list: () => fetchRecordedLetters(recorded), one: (to) => fetchRecordedLetter(recorded, to) } : null
  const [letters, setLetters] = useState(null)
  const [to, setTo] = useState(null)
  const [texts, setTexts] = useState({})
  const [listError, setListError] = useState(null)
  const [said, setSaid] = useState(null) // { tone: 'status' | 'alert' | 'prompt', text }
  const [requests, setRequests] = useState([]) // the case's freeze log, to tell what was already sent
  const [logged, setLogged] = useState(0) // remounts the log after a letter is marked sent
  const [manual, setManual] = useState(false) // the clipboard refused: the text waits, selected, in a box
  const [drafts, setDrafts] = useState(0) // redrafts the letter after a sign-off changes what it says
  const [askReason, setAskReason] = useState(null) // why this caller cannot ask for a sign-off (not signed in)
  const box = useRef(null)
  const picked = useRef(null)
  const stateLine = useRef(null) // takes the keyboard when a sign-off button leaves the card

  const loadRequests = () => caseId && fetchCaseRequests(caseId).then((d) => {
    setRequests(d.requests ?? []); setAskReason(d.ask_reason ?? null); return d.requests ?? []
  })
  useEffect(() => { loadRequests()?.catch(() => {}) }, [caseId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (manual) { box.current?.focus(); box.current?.select() } }, [manual])

  useEffect(() => {
    if (!source) return undefined
    let live = true
    source.list().then((d) => {
      if (!live) return
      setLetters(d.letters ?? [])
      setTo(d.letters?.[0]?.to ?? null)
    }).catch((e) => live && setListError(`The letters could not be listed: ${e.message}`))
    return () => { live = false }
  }, [caseId, recorded]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!source || !to || texts[to] !== undefined) return undefined
    let live = true
    source.one(to).then((text) => live && setTexts((t) => ({ ...t, [to]: text })))
      .catch((e) => live && setSaid({ tone: 'alert', text: `The letter could not be drafted: ${e.message}` }))
    return () => { live = false }
  }, [to, drafts]) // eslint-disable-line react-hooks/exhaustive-deps

  // The letter a Flow card asked for opens on the sheet and takes the keyboard.
  const listed = (wanted) => (letters?.some((l) => l.to === wanted) ? wanted : null)
  const ask = asked && (listed(asked) ?? listed(FALLBACK[asked]))
  useEffect(() => {
    if (ask) { setTo(ask); setSaid(null); setManual(false) }
  }, [ask])
  useEffect(() => { picked.current?.focus() }, [letters, asked])

  const letter = letters?.find((l) => l.to === to)
  const text = texts[to]
  const names = text ? blanks(text) : []
  const ticks = text ? checks(text, result) : []

  // This letter's row in the freeze log: one still open, to the same recipient, of the same kind.
  const rowOf = (rows) => letter && rows.find((r) => r.recipient === recipientOf(letter, result)
    && r.kind === kindOf(to) && r.status !== 'closed')
  // An urgent freeze letter is ready only once a second officer of the unit
  // signs it off (freeze_requests.py); until then it cannot be marked sent.
  const urgent = Boolean(to?.endsWith('-freeze'))
  const row = rowOf(requests)
  const status = row?.status ?? 'drafted'
  const sent = !['drafted', 'awaiting_signoff', 'ready'].includes(status)
  const held = Boolean(caseId) && urgent && !row?.signoff && !sent
  // Said before anyone presses Ask: a letter no unit's officer could sign would wait for good.
  const cannotAsk = row ? row.ask_reason : askReason

  function pick(next) { setTo(next); setSaid(null); setManual(false) }
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setManual(false)
      setSaid({ tone: 'status', text: 'Copied the letter.' })
    } catch {
      setManual(true)
      setSaid({ tone: 'alert', text: 'This browser would not copy. The letter is selected in the box below: press Ctrl+C (⌘C on a Mac).' })
    }
  }
  /** Move this letter's row on to `next` (`from` the statuses it may leave),
   * or log it at `next`: read afresh, since the log may have changed. */
  async function moveTo(next, from) {
    const fresh = rowOf(await loadRequests())
    if (fresh?.mine === false) return false
    if (fresh && from.includes(fresh.status)) await updateRequest(fresh.request_id, { status: next })
    else if (!fresh) {
      await logRequest({
        case_id: caseId, recipient: recipientOf(letter, result), kind: kindOf(to),
        address: addressOf(letter, result),
        asset: assetOf(to, result), status: next,
      })
    }
    return true
  }
  async function done(text, redraft = false) {
    await loadRequests()
    setLogged((n) => n + 1)
    if (redraft) { setTexts(({ [to]: _, ...rest }) => rest); setDrafts((n) => n + 1) }
    setSaid({ tone: 'status', text })
    if (redraft) stateLine.current?.focus() // the button pressed is gone: keep the keyboard's place
  }
  async function markSent() {
    if (!caseId) { setSaid({ tone: 'prompt' }); return }
    if (sent) return
    if (held) { setSaid({ tone: 'status', text: 'A second officer must sign this letter off before it can be marked as sent.' }); return }
    try {
      if (!(await moveTo('sent', ['drafted', 'ready']))) {
        setSaid({ tone: 'status', text: 'The officer who drafted this letter logs it as sent.' })
        return
      }
      await done(`Logged as sent to ${recipientOf(letter, result)}.`)
    } catch (e) {
      setSaid({ tone: 'alert', text: `It could not be logged: ${e.message}` })
    }
  }
  async function askSignoff() {
    try {
      await moveTo('awaiting_signoff', ['drafted'])
      await done("Asked for a second officer's sign-off.", true)
    } catch (e) {
      setSaid({ tone: 'alert', text: `The sign-off could not be asked for: ${e.message}` })
    }
  }
  async function signOff() {
    try {
      await signOffRequest(row.request_id)
      await done('Signed off. The letter is ready to send.', true)
    } catch (e) {
      setSaid({ tone: 'alert', text: `It could not be signed off: ${e.message}` })
    }
  }

  return (
    <div className="letters">
      {listError && <p className="error-line" role="alert">{listError}</p>}
      {letters?.length === 0 && <p className="card note case-note">This case supports no request letter: it reached no exchange and holds no USDT that Tether could act on.</p>}
      {letter && (
        <div className="lt-body">
          <div className="lt-switch" role="group" aria-label="Letter to">
            {letters.map((l) => (
              <button key={l.to} ref={l.to === ask ? picked : undefined} type="button" aria-pressed={l.to === to} onClick={() => pick(l.to)}>{plain(l.title)}</button>
            ))}
          </div>
          <article className="letter-sheet" aria-labelledby="letter-title">
            <h2 id="letter-title" className="visually-hidden">Draft: {plain(letter.title)}</h2>
            {text === undefined ? <p className="lt-wait">Drafting the letter…</p> : (
              <div className="letter-text">
                {lines(text).map((line, n) => (
                  <p className="ln" key={n} style={line.indent || line.hang ? { paddingLeft: `${(line.indent + line.hang) * 0.5}em`, textIndent: `${-line.hang * 0.5}em` } : undefined}>
                    {line.parts.map((p, i) => (typeof p === 'string' ? p : (
                      <mark className="letter-blank" key={i}>
                        <span className="visually-hidden no-copy">Blank {p.blank + 1} of {names.length}, for you to fill: {names[p.blank]}. </span>
                        <span aria-hidden="true">{p.text}</span>
                      </mark>
                    )))}
                  </p>
                ))}
              </div>
            )}
          </article>

          <aside className="lt-side" aria-label="Letter checks">
            {ticks.length > 0 && (
              <section className="lt-card" aria-labelledby="lt-checked">
                <h2 id="lt-checked">Checked for you</h2>
                <ul className="lt-ticks">
                  {ticks.map((c) => <li key={c.title}><span>{c.title}</span><small>{c.detail}</small><Tick /></li>)}
                </ul>
              </section>
            )}
            {text !== undefined && (
              <section className="lt-card risk" aria-labelledby="lt-fill">
                <h2 id="lt-fill">For you to fill · {names.length}</h2>
                {names.length > 0 ? <ul className="lt-fill">{names.map((n, i) => <li key={i}>{n}</li>)}</ul>
                  : <p className="note">Nothing is left blank.</p>}
              </section>
            )}
            {urgent && (
              <section className="lt-card" aria-labelledby="lt-signoff">
                <h2 id="lt-signoff">Second officer</h2>
                <p className="lt-state" id="lt-signoff-state" ref={stateLine} tabIndex={-1}>
                  {row?.signoff ? `Approved by ${plain(row.signoff.by)}, ${ist(row.signoff.at)} IST.`
                    : status === 'awaiting_signoff' ? "Awaiting a second officer's approval."
                      : 'A second officer of your unit must approve this urgent letter before it is ready to send.'}
                </p>
                {!caseId ? <p className="note">A recorded example cannot be signed off: Trace live stores it as a case.</p>
                  : status === 'awaiting_signoff' ? (row.can_sign_off
                    ? <button type="button" className="lt-sign" onClick={signOff}>Sign off</button>
                    : row.signoff_reason && <p className="note">{row.signoff_reason}</p>)
                    : status === 'drafted' && row?.mine !== false && (cannotAsk
                      ? <p className="note">{cannotAsk}</p>
                      : <button type="button" className="lt-sign" onClick={askSignoff}>Ask for sign-off</button>)}
              </section>
            )}
            <div className="lt-actions">
              <button type="button" className="lt-solid" onClick={printSheet} disabled={!text}>
                <svg aria-hidden="true" width="14" height="14" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M9 2v9M5 7l4 4 4-4M3 14h12" /></svg>
                PDF<span className="visually-hidden"> (print the letter, or save it as a PDF)</span>
              </button>
              <button type="button" onClick={copy} disabled={!text}>Copy text</button>
              {/* Marked, it stays focusable (aria-disabled), so the keyboard keeps its place. */}
              <button type="button" className="lt-go" onClick={markSent} disabled={!text} aria-disabled={sent || held || undefined} aria-describedby={held ? 'lt-signoff-state' : undefined}>{sent ? 'Marked as sent' : 'Mark as sent'}</button>
            </div>
            {/* Both lines stay in the page, empty until something is said, so it is announced. */}
            <div className="lt-news">
              <p className="error-line" role="alert">{said?.tone === 'alert' ? said.text : ''}</p>
              <p className="lt-said" role="status">
                {said?.tone === 'status' && said.text}
                {said?.tone === 'prompt' && <>
                  A recorded example is not a stored case, so a letter cannot be logged as sent from it:
                  Trace live stores it as one. <Link to="/cases">Open a stored case</Link>
                </>}
              </p>
            </div>
            {manual && <textarea ref={box} className="lt-manual" readOnly rows={8} value={text} aria-label="The letter's text, selected to copy" />}
          </aside>
        </div>
      )}

      {caseId ? <>
        <RequestsPanel key={logged} result={result} onChange={() => loadRequests()?.catch(() => {})} />
        <WatchPanel result={result} extra={watch} />
      </> : (
        <p className="card note case-note">
          Freeze requests and watches need a stored case. {recorded
            ? 'This is a recorded example: Trace live runs it again now and stores it as a case.'
            : 'This trace was not saved, so it has no letters either.'}
        </p>
      )}
    </div>
  )
}

// Skips a render while its props are the same (see TimelineTab).
export default memo(LettersTab)
