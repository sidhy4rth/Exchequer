import { useEffect, useRef, useState } from 'react'
import { createOfficer, createUnit, fetchOfficers, fetchUnits, updateOfficer } from '../api/accounts'
import { isAdmin, recheckAccount, ROLE_NAMES, signedInAs, useAccount } from '../session'
import { plain } from '../text'
import './Admin.css'

// The admin's page: the units, and every officer's account. There is no
// public sign-up; an admin makes each account here, and its temporary
// password is shown once, for the admin to hand over. The backend
// (routes/accounts.py) checks every call; this page only lays them out.

const ROLES = Object.entries(ROLE_NAMES)
const IST = new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' })
/** The refusal in words; an ended session or a lost admin role is also
 * taken up by the sidebar at once (session.js). */
function refused(failed, setError) {
  setError(failed.message)
  if (failed.status === 401 || failed.status === 403) recheckAccount()
}
// Whose a row's control is, for a screen reader's list of controls.
const Whose = ({ name }) => <span className="visually-hidden">, {name}</span>
const lastIn = (at) => (at ? `Last signed in ${IST.format(new Date(at))} IST` : 'Never signed in')

/** A temporary password, shown this once: copy it, hand it over, done. */
function OneTime({ shown, onDone }) {
  const box = useRef(null)
  // null until tried; then true, or false where the browser will not copy.
  const [copied, setCopied] = useState(null)
  useEffect(() => { box.current?.focus() }, [])
  async function copy() {
    try { await navigator.clipboard.writeText(shown.password); setCopied(true) } catch { setCopied(false) }
  }
  const name = plain(shown.name)
  return (
    <section ref={box} tabIndex={-1} className="card admin-once" aria-labelledby="admin-once-head">
      <h2 id="admin-once-head">Temporary password for {name}</h2>
      <p className="admin-once-row">
        <span className="mono">{shown.password}</span>
        <button type="button" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
      </p>
      {copied === false && <p className="note" role="status">Copy did not work here. Select the password and copy it by hand.</p>}
      <p className="admin-warn">
        Shown once: it cannot be shown again. Give it to {name} in person or by phone, never in a group chat.
        They choose their own password the first time they sign in.
      </p>
      <button type="button" className="quiet" onClick={onDone}>Done</button>
    </section>
  )
}

/** One officer: who, and their role, unit and sign-in, saved together. A
 * reset or a switch-off ends the account's sessions, so the admin's own row
 * offers neither (another admin can). */
function Officer({ officer, units, me, onSaved, onPassword }) {
  const [draft, setDraft] = useState({ role: officer.role, unit_id: officer.unit?.id, active: officer.active })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const name = plain(officer.name)
  const changes = Object.fromEntries(Object.entries(draft).filter(([k, v]) => v !== (k === 'unit_id' ? officer.unit?.id : officer[k])))
  const id = `officer-${officer.id}`
  const resetButton = useRef(null)

  async function send(body) {
    setBusy(true)
    setError(null)
    try {
      const { officer: saved, temporary_password: password } = await updateOfficer(officer.id, body)
      onSaved(saved)
      setDraft({ role: saved.role, unit_id: saved.unit?.id, active: saved.active })
      if (password) onPassword({ name: saved.name, password, back: resetButton.current })
      if (me) signedInAs(saved) // a new role or unit shows in the sidebar now
    } catch (failed) {
      refused(failed, setError)
    }
    setBusy(false)
  }
  function save(event) {
    event.preventDefault()
    if (Object.keys(changes).length) send(changes)
  }
  function reset() {
    if (window.confirm(`Reset ${name}'s password? They are signed out, and get a new temporary password, shown here once.`)) send({ reset_password: true })
  }

  return (
    <li className="admin-officer">
      <form aria-label={name} onSubmit={save}>
        <div className="admin-who">
          <h3>{name}</h3>
          <span className="mono">{plain(officer.email)}</span>
          <span className="admin-pills">
            {!officer.active && <span className="pill red">Switched off</span>}
            {officer.must_change_password && <span className="pill amber">Must change password</span>}
          </span>
          {me && <span className="note">This is you.</span>}
          <span className="note">{lastIn(officer.last_login_at)}</span>
        </div>
        <div className="admin-edit">
          <label htmlFor={`${id}-role`}>Role<Whose name={name} /></label>
          <select id={`${id}-role`} value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })}>
            {ROLES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <label htmlFor={`${id}-unit`}>Unit<Whose name={name} /></label>
          <select id={`${id}-unit`} value={draft.unit_id} onChange={(e) => setDraft({ ...draft, unit_id: Number(e.target.value) })}>
            {units.map((u) => <option key={u.id} value={u.id}>{plain(u.name)}</option>)}
          </select>
          {!me && <label className="admin-check">
            <input type="checkbox" checked={draft.active} onChange={(e) => setDraft({ ...draft, active: e.target.checked })} />
            Can sign in<Whose name={name} />
          </label>}
          <span className="admin-actions">
            <button type="submit" className="primary" disabled={busy || !Object.keys(changes).length}>Save<Whose name={name} /></button>
            {!me && <button type="button" className="quiet" ref={resetButton} disabled={busy} onClick={reset}>Reset password<Whose name={name} /></button>}
          </span>
        </div>
        {error && <p className="error-line" role="alert">{error}</p>}
      </form>
    </li>
  )
}

/** A new account: name, e-mail, unit and role. */
function NewOfficer({ units, onMade }) {
  const blank = { name: '', email: '', unit_id: '', role: 'officer' }
  const [fields, setFields] = useState(blank)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const createButton = useRef(null)
  const bind = (key) => ({ id: `new-${key}`, value: fields[key], onChange: (e) => setFields({ ...fields, [key]: e.target.value }) })
  const unitId = fields.unit_id || units[0]?.id
  async function submit(event) {
    event.preventDefault()
    if (!fields.name.trim() || !fields.email.trim() || !unitId) { setError('Fill in the name, e-mail and unit.'); return }
    setBusy(true)
    setError(null)
    try {
      const made = await createOfficer({ name: fields.name.trim(), email: fields.email.trim(), unit_id: Number(unitId), role: fields.role })
      onMade(made, createButton.current)
      setFields(blank)
    } catch (failed) {
      refused(failed, setError)
    }
    setBusy(false)
  }
  return (
    <form className="admin-new" aria-label="Add an officer" onSubmit={submit} noValidate>
      <h3>Add an officer</h3>
      <label htmlFor="new-name">Name</label>
      <input {...bind('name')} autoComplete="off" />
      <label htmlFor="new-email">E-mail</label>
      <input {...bind('email')} type="email" autoComplete="off" spellCheck={false} />
      <label htmlFor="new-unit_id">Unit</label>
      <select {...bind('unit_id')} value={unitId ?? ''}>
        {units.map((u) => <option key={u.id} value={u.id}>{plain(u.name)}</option>)}
      </select>
      <label htmlFor="new-role">Role</label>
      <select {...bind('role')}>
        {ROLES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      {error && <p className="error-line" role="alert">{error}</p>}
      <button type="submit" className="primary" ref={createButton} disabled={busy}>Create account</button>
    </form>
  )
}

export default function Admin() {
  const { officer } = useAccount()
  const allowed = isAdmin(officer)
  const [units, setUnits] = useState([])
  const [officers, setOfficers] = useState(null)
  const [unitName, setUnitName] = useState('')
  const [error, setError] = useState(null)
  const [shown, setShown] = useState(null)
  // Where focus goes when the one-time password is put away: the button
  // that made it, or the Officers heading if that row has gone.
  const back = useRef(null)
  const heading = useRef(null)
  const show = (next) => { back.current = next.back; setShown(next) }
  useEffect(() => {
    if (shown || !back.current) return
    const to = back.current.isConnected ? back.current : heading.current
    back.current = null
    to?.focus()
  }, [shown])

  useEffect(() => {
    if (!allowed) return
    Promise.all([fetchUnits(), fetchOfficers()])
      .then(([u, o]) => { setUnits(u.units); setOfficers(o.officers) })
      .catch((failed) => refused(failed, setError))
  }, [allowed])

  async function addUnit(event) {
    event.preventDefault()
    if (!unitName.trim()) { setError('Name the unit first.'); return }
    try {
      const unit = await createUnit(unitName.trim())
      setUnits((list) => [...list, unit])
      setUnitName('')
      setError(null)
    } catch (failed) {
      refused(failed, setError)
    }
  }
  const saved = (next) => setOfficers((list) => list.map((o) => (o.id === next.id ? next : o)))
  const made = ({ officer: next, temporary_password: password }, from) => {
    setOfficers((list) => [...list, next])
    show({ name: next.name, password, back: from })
  }
  const count = (unit) => (officers ?? []).filter((o) => o.unit?.id === unit.id).length

  return (
    <div className="work console admin">
      <header className="work-head">
        <p className="note">Units and officer accounts. Officers sign in with what you make here.</p>
        <h1>Admin</h1>
      </header>
      {!allowed ? <p className="banner">Only an admin can open this page.</p> : (
        <>
          {error && <p className="banner error" role="alert">{error}</p>}
          {shown && <OneTime key={shown.password} shown={shown} onDone={() => setShown(null)} />}
          <div className="admin-grid">
            <section className="card admin-card" aria-labelledby="admin-units">
              <h2 id="admin-units">Units</h2>
              <ul className="admin-units" aria-labelledby="admin-units">
                {units.map((u) => (
                  <li key={u.id}><span>{plain(u.name)}</span><span className="note">{count(u)} {count(u) === 1 ? 'officer' : 'officers'}</span></li>
                ))}
              </ul>
              <form className="admin-unit-new" onSubmit={addUnit} noValidate>
                <label htmlFor="unit-name">New unit</label>
                <span>
                  <input id="unit-name" value={unitName} autoComplete="off" onChange={(e) => setUnitName(e.target.value)} />
                  <button type="submit">Add unit</button>
                </span>
              </form>
            </section>
            <section className="card admin-card" aria-labelledby="admin-officers">
              <h2 id="admin-officers" ref={heading} tabIndex={-1}>Officers{officers ? ` · ${officers.length}` : ''}</h2>
              {officers === null ? <p className="note">Loading accounts…</p> : (
                <ul className="admin-list">
                  {officers.map((o) => (
                    <Officer key={o.id} officer={o} units={units} me={o.id === officer.id} onSaved={saved} onPassword={show} />
                  ))}
                </ul>
              )}
              {units.length > 0 && <NewOfficer units={units} onMade={made} />}
            </section>
          </div>
        </>
      )}
    </div>
  )
}
