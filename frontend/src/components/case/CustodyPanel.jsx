import { useEffect, useRef, useState } from 'react'
import { addCustodyWallet, fetchCaseAssets, fetchCaseCustody, movementStep, proposeMovement } from '../../api'
import { plain } from '../../text'
import { middle } from './format'
import { money, todayInIndia } from './AssetsPanel'
import './CustodyPanel.css'

// Custody wallets (backend custody.py, custody_log.py; suite feature 9): the
// unit's multisig wallets this case's seized crypto is held in, their signers
// by name, and the signing log of every deposit and release. The signatures
// happen on the signers' hardware wallets; nothing here ever takes a key.
// Hidden unless the server's EXCHEQUER_CUSTODY_WALLETS flag is on.

export const STATUS = { proposed: 'Proposed', approved: 'Approved', broadcast: 'Broadcast', confirmed: 'Confirmed', cancelled: 'Cancelled' }
const TONE = { approved: 'green', confirmed: 'green', cancelled: 'red' }

/** "Name, role, unit" per line into signer objects; blank lines dropped. */
export function parseSigners(text) {
  return String(text).split('\n').map((line) => line.split(',').map((p) => p.trim()))
    .filter(([name]) => name).map(([name, role = '', ...unit]) => ({ name, role, unit: unit.join(', ') }))
}

const same = (a, b) => a.replace(/\s+/g, ' ').trim().toLowerCase() === b.replace(/\s+/g, ' ').trim().toLowerCase()

/** The wallet's signers who may still approve `m`: not yet counted, and not its proposer unless the scheme allows. */
export function canApprove(w, m) {
  return w.signers.map((s) => s.name).filter((name) => !m.approvals.some((a) => same(a.signer, name))
    && (w.proposer_may_sign || !same(name, m.proposed_by)))
}

const NEW_WALLET = { chain: 'tron', address: '', scheme: '', threshold: '2', signers: '', proposer_may_sign: false, set_up_by: '', notes: '', asset_ids: [] }
const NEW_MOVE = { kind: 'deposit', asset: '', amount: '', destination: '', order_ref: '', proposed_by: '' }

export default function CustodyPanel({ result }) {
  const caseId = result?.case_id
  const [data, setData] = useState(null)
  const [held, setHeld] = useState([]) // asset-register rows held in custody, to link to a new wallet
  const [form, setForm] = useState(null)
  const [moves, setMoves] = useState({}) // wallet_id → proposal form values
  const [input, setInput] = useState({}) // movement_id → { signer, tx_hash, reason }
  const [error, setError] = useState(null)
  const [focusOn, setFocusOn] = useState(null) // the wallet or movement to take the keyboard once it renders
  const rows = useRef({}) // wallet_id / movement_id → its element

  const load = () => caseId && fetchCaseCustody(caseId).then(setData).catch(() => {})
  // Asked again each time the form opens: a row added to the register above since then is offered too.
  const loadHeld = () => caseId && fetchCaseAssets(caseId).then((a) => setHeld((a.assets ?? []).filter((r) => r.holder === 'custody'))).catch(() => {})
  useEffect(() => { load(); loadHeld() }, [caseId]) // eslint-disable-line react-hooks/exhaustive-deps
  // A step's button, or the form just sent, leaves the page: the row it changed takes the keyboard instead of the body.
  useEffect(() => {
    if (focusOn && rows.current[focusOn]) { rows.current[focusOn].focus(); setFocusOn(null) }
  }, [focusOn, data])

  if (!caseId || !data?.enabled) return null

  /** fn's answer once the panel has reloaded, or null when the server refused (the refusal is shown). */
  async function run(fn) {
    setError(null)
    try { const out = await fn(); await load(); return out ?? {} } catch (e) { setError(e.message); return null }
  }
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))
  const setMove = (wid, key) => (e) => setMoves((m) => ({ ...m, [wid]: { ...m[wid], [key]: e.target.value } }))
  const setIn = (mid, key) => (e) => setInput((m) => ({ ...m, [mid]: { ...m[mid], [key]: e.target.value } }))
  const link = (id) => (e) => setForm((f) => ({ ...f, asset_ids: e.target.checked ? [...f.asset_ids, id] : f.asset_ids.filter((x) => x !== id) }))
  async function save(e) {
    e.preventDefault()
    const body = { ...form, signers: parseSigners(form.signers), set_up_on: form.set_up_on || todayInIndia() }
    const made = await run(() => addCustodyWallet(caseId, body))
    if (made) { setForm(null); setFocusOn(made.wallet_id) }
  }
  async function propose(e, wid) {
    e.preventDefault()
    const made = await run(() => proposeMovement(wid, moves[wid]))
    if (made) { setMoves((m) => ({ ...m, [wid]: undefined })); setFocusOn(made.movement_id) }
  }
  // Once a step is recorded its inputs are spent: a signer left chosen would be sent again.
  async function step(mid, name, body) {
    if (await run(() => movementStep(mid, name, body))) { setInput((m) => ({ ...m, [mid]: undefined })); setFocusOn(mid) }
  }
  const keep = (id) => (el) => { rows.current[id] = el }

  return (
    <details className="card sec custody-panel" open={data.wallets.length > 0}>
      <summary>
        <span className="micro">Custody wallets · {data.wallets.length}</span>
        <span className="note">multisig wallets for seized crypto, and every movement signed</span>
      </summary>
      <div className="body requests-panel">
        {data.wallets.map((w) => (
          <div className="request-row" key={w.wallet_id} ref={keep(w.wallet_id)} tabIndex={-1} role="group" aria-label={`Custody wallet ${w.address}`}>
            <div className="top">
              <span className="nm"><span className="mono" title={w.address}>{middle(w.address)}</span> <span className="note">· {plain(w.chain_name)}</span></span>
              <span className="pill">{w.threshold} of {w.signer_count} signers</span>
            </div>
            <dl className="cu-facts">
              <dt>Scheme</dt><dd>{plain(w.scheme)}{w.proposer_may_sign ? ' · a proposer may also sign' : ''}</dd>
              <dt>Signers</dt><dd>{w.signers.map((s) => [s.name, s.role, s.unit].filter(Boolean).map(plain).join(', ')).join(' · ')}</dd>
              <dt>Set up</dt><dd>{plain(w.set_up_by)}, {w.set_up_on}</dd>
              {w.asset_ids.length > 0 && <><dt>Holds</dt><dd>{w.asset_ids.length} asset-register row{w.asset_ids.length === 1 ? '' : 's'}</dd></>}
            </dl>
            {w.movements.map((m) => {
              const v = input[m.movement_id] ?? {}
              const signers = canApprove(w, m)
              return (
                <div className="cu-move" key={m.movement_id} ref={keep(m.movement_id)} tabIndex={-1} role="group" aria-label={`${m.kind} of ${m.amount} ${m.asset}`}>
                  <div className="top">
                    <span><b>{m.kind === 'release' ? 'Release' : 'Deposit'}</b> <span className="mono">{money(m.amount, m.asset)}</span>{m.kind === 'release' && <> to <span className="mono" title={m.destination}>{middle(m.destination)}</span></>}</span>
                    <span className={`pill ${TONE[m.status] ?? ''}`}>{STATUS[m.status] ?? m.status}</span>
                  </div>
                  <p className="note">
                    Proposed by {plain(m.proposed_by)}{m.order_ref ? ` · court's order ${plain(m.order_ref)}` : ''}
                    {' · '}{m.kind === 'deposit' && !m.approvals.length ? 'a deposit into the wallet needs no signatures'
                      : `approved by ${m.approvals.length ? m.approvals.map((a) => plain(a.signer)).join(', ') : 'nobody yet'} (${m.approvals.length} of ${m.threshold})`}
                    {m.tx_hash ? <> · tx <span className="mono" title={m.tx_hash}>{middle(m.tx_hash)}</span></> : null}
                  </p>
                  {!['confirmed', 'cancelled'].includes(m.status) && (
                    <div className="cu-steps">
                      {m.status === 'proposed' && signers.length > 0 && <>
                        <select aria-label="Signer who approved" value={v.signer ?? ''} onChange={setIn(m.movement_id, 'signer')}>
                          <option value="">Signer who approved…</option>
                          {signers.map((name) => <option key={name} value={name}>{name}</option>)}
                        </select>
                        <button type="button" disabled={!v.signer} onClick={() => step(m.movement_id, 'approve', { signer: v.signer })}>Record approval</button>
                      </>}
                      {(m.status === 'approved' || (m.status === 'proposed' && m.kind === 'deposit')) && <>
                        <input aria-label="Transaction hash" className="mono" placeholder="transaction hash, once sent" value={v.tx_hash ?? ''} onChange={setIn(m.movement_id, 'tx_hash')} />
                        <button type="button" disabled={!v.tx_hash} onClick={() => step(m.movement_id, 'broadcast', { tx_hash: v.tx_hash })}>Record broadcast</button>
                      </>}
                      {m.status === 'broadcast' && <button type="button" onClick={() => step(m.movement_id, 'confirm')}>Confirmed on chain</button>}
                      <input aria-label="Why it is cancelled" placeholder="why cancel" value={v.reason ?? ''} onChange={setIn(m.movement_id, 'reason')} />
                      <button type="button" className="quiet" disabled={!v.reason} onClick={() => step(m.movement_id, 'cancel', { reason: v.reason })}>Cancel</button>
                    </div>
                  )}
                </div>
              )
            })}
            {moves[w.wallet_id] ? (
              <form className="cu-form" aria-label="Propose a movement" onSubmit={(e) => propose(e, w.wallet_id)}>
                <div className="fields">
                  <label>Movement
                    <select value={moves[w.wallet_id].kind} onChange={setMove(w.wallet_id, 'kind')}>
                      <option value="deposit">Deposit into the wallet</option>
                      <option value="release">Release on the court&apos;s order</option>
                    </select>
                  </label>
                  <label>Proposed by<input value={moves[w.wallet_id].proposed_by} onChange={setMove(w.wallet_id, 'proposed_by')} /></label>
                  <label>Asset<input value={moves[w.wallet_id].asset} onChange={setMove(w.wallet_id, 'asset')} placeholder="USDT" /></label>
                  <label>Amount<input value={moves[w.wallet_id].amount} onChange={setMove(w.wallet_id, 'amount')} inputMode="decimal" className="mono" /></label>
                  {moves[w.wallet_id].kind === 'release' && <>
                    <label className="wide">Released to (address)<input value={moves[w.wallet_id].destination} onChange={setMove(w.wallet_id, 'destination')} className="mono" /></label>
                    <label className="wide">Court&apos;s order<input value={moves[w.wallet_id].order_ref} onChange={setMove(w.wallet_id, 'order_ref')} placeholder="number, date and court" /></label>
                  </>}
                </div>
                <div className="request-add">
                  <button type="submit" className="cu-save">Propose</button>
                  <button type="button" className="quiet" onClick={() => setMoves((m) => ({ ...m, [w.wallet_id]: undefined }))}>Close</button>
                </div>
              </form>
            ) : (
              <div className="request-add"><button type="button" onClick={() => setMoves((m) => ({ ...m, [w.wallet_id]: { ...NEW_MOVE } }))}>Propose a deposit or release</button></div>
            )}
          </div>
        ))}

        {!form && <div className="request-add"><button type="button" onClick={() => { setForm({ ...NEW_WALLET, set_up_on: todayInIndia() }); loadHeld() }}>Record a custody wallet</button></div>}
        {form && (
          <form className="cu-form" aria-label="Record a custody wallet" onSubmit={save}>
            <div className="fields">
              <label>Chain
                <select value={form.chain} onChange={set('chain')}>
                  {Object.entries(data.chains ?? {}).map(([k, name]) => <option key={k} value={k}>{name}</option>)}
                </select>
              </label>
              <label>Threshold (m)<input value={form.threshold} onChange={set('threshold')} inputMode="numeric" /></label>
              <label className="wide">Multisig wallet&apos;s address<input value={form.address} onChange={set('address')} className="mono" /></label>
              <label className="wide">Scheme<input value={form.scheme} onChange={set('scheme')} placeholder="e.g. Safe on Ethereum, Tron multi-sign permission" /></label>
              <label className="wide">Signers, one per line: name, role, unit
                <textarea rows={3} value={form.signers} onChange={set('signers')} placeholder={'Insp. Rao, Inspector, Cyber Cell\nSI Iyer, Sub-Inspector, Cyber Cell'} />
              </label>
              <label className="cu-check wide"><input type="checkbox" checked={form.proposer_may_sign} onChange={set('proposer_may_sign')} /> The scheme lets the officer who proposes a movement also approve it</label>
              <label>Set up by<input value={form.set_up_by} onChange={set('set_up_by')} /></label>
              <label>Set up on<input type="date" value={form.set_up_on} onChange={set('set_up_on')} /></label>
              {held.map((a) => (
                <label className="cu-check wide" key={a.asset_id}><input type="checkbox" checked={form.asset_ids.includes(a.asset_id)} onChange={link(a.asset_id)} /> Holds {money(a.amount, a.asset)} from the asset register</label>
              ))}
              <label className="wide">Notes<textarea rows={2} value={form.notes} onChange={set('notes')} /></label>
            </div>
            <p className="note cu-never">Names only. Never type, photograph or paste a private key or seed phrase: it stays on the signers&apos; hardware wallets.</p>
            <div className="request-add">
              <button type="submit" className="cu-save">Record the wallet</button>
              <button type="button" className="quiet" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}
        {error && <p className="error-line" role="alert">{error}</p>}
        <p className="note">Every step is entered by a signed-in officer. A release needs the court&apos;s order and the wallet&apos;s threshold of distinct signers. Kept with this browser&apos;s and unit&apos;s records.</p>
      </div>
    </details>
  )
}
