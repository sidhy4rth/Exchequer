import { useEffect, useRef, useState } from 'react'
import { addTask, fetchCaseTasks, updateTask } from '../../api'
import { plain } from '../../text'
import './TasksPanel.css'

// The case's task list (backend tasks.py, suite feature 6): what still has to
// be done in this case, who it is assigned to (a name), by when, and what came
// of it. Done needs no reason; dropping a task or opening it again does.
// Nothing is deleted: every change is in the task's history.

const day = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const days = (n) => `${n} day${n === 1 ? '' : 's'}`

/** What a task's date means now: { tone, text } for a pill. */
export function dueText(t) {
  if (t.status === 'done') return { tone: 'green', text: 'Done' }
  if (t.status === 'dropped') return { tone: '', text: 'Dropped' }
  if (!t.due_on) return { tone: '', text: 'No due date' }
  if (t.days_left < 0) return { tone: 'red', text: `Overdue by ${days(-t.days_left)}` }
  if (t.days_left === 0) return { tone: 'red', text: 'Due today' }
  if (t.days_left <= 7) return { tone: 'amber', text: `Due in ${days(t.days_left)}` }
  return { tone: '', text: `Due ${day(t.due_on)}` }
}

const ACTION = { added: 'added', changed: 'changed', done: 'done', dropped: 'dropped', reopened: 'opened again', noted: 'note added' }

/** One history entry as a short line: "14 Nov 2026 dropped: Bank answered on the portal". */
export function historyLine(h) {
  const what = h.action === 'changed' && h.changed ? `changed ${h.changed.join(', ').replaceAll('_on', ' date')}` : ACTION[h.action] ?? h.action
  return `${String(h.at).slice(0, 10)} ${what}${h.note ? `: ${h.note}` : ''}`
}

const EMPTY = { title: '', assignee: '', due_on: '', notes: '' }

export default function TasksPanel({ result }) {
  const caseId = result?.case_id
  const [rows, setRows] = useState([])
  const [form, setForm] = useState(null) // the add form's values while it is open
  const [why, setWhy] = useState({}) // task_id → { status, note } while a reason is being typed
  const [error, setError] = useState(null)
  // Open on arrival when something is open; after that only the officer folds it,
  // so closing the last task never snaps the panel shut under their cursor.
  const [expanded, setExpanded] = useState(false)
  const arrived = useRef(false)

  const load = () => caseId && fetchCaseTasks(caseId).then((d) => {
    const tasks = d.tasks ?? []
    setRows(tasks)
    if (!arrived.current) {
      arrived.current = true
      if (tasks.some((t) => t.status === 'open')) setExpanded(true)
    }
  }).catch(() => {})
  useEffect(() => { load() }, [caseId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!caseId) return null

  async function run(fn) {
    setError(null)
    try { await fn(); await load(); return true } catch (e) { setError(e.message); return false }
  }
  const change = (t, changes) => run(() => updateTask(t.task_id, changes))
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))
  async function save(e) {
    e.preventDefault()
    if (await run(() => addTask(caseId, form))) setForm(null)
  }
  async function decide(t) {
    const w = why[t.task_id]
    if (await change(t, { status: w.status, note: w.note.trim() })) setWhy((o) => ({ ...o, [t.task_id]: undefined }))
  }

  const open = rows.filter((t) => t.status === 'open')
  const closed = rows.filter((t) => t.status !== 'open')
  const overdue = open.filter((t) => t.overdue).length

  const row = (t) => {
    const d = dueText(t)
    const w = why[t.task_id]
    return (
      <div className="request-row" key={t.task_id}>
        <div className="top">
          <span className="nm">{plain(t.title)}</span>
          <span className={`pill ${d.tone}`}>{d.text}</span>
        </div>
        <dl className="tk-facts">
          {/* An open task shows these in its fields below; a closed one only here. */}
          {t.status !== 'open' && t.assignee && <><dt>Assigned to</dt><dd>{plain(t.assignee)}</dd></>}
          {t.status !== 'open' && t.due_on && <><dt>Due</dt><dd>{day(t.due_on)}</dd></>}
          {t.notes && <><dt>Notes</dt><dd>{plain(t.notes)}</dd></>}
        </dl>
        {t.status === 'open' && !w && (
          <div className="fields">
            <label>Assigned to
              <input defaultValue={t.assignee} placeholder="a name"
                onBlur={(e) => e.target.value !== t.assignee && change(t, { assignee: e.target.value })} />
            </label>
            <label>Due
              <input type="date" defaultValue={t.due_on}
                onBlur={(e) => e.target.value !== t.due_on && change(t, { due_on: e.target.value })} />
            </label>
            <div className="tk-actions">
              <button type="button" className="tk-done" onClick={() => change(t, { status: 'done' })}>Mark done</button>
              <button type="button" className="quiet" onClick={() => setWhy((o) => ({ ...o, [t.task_id]: { status: 'dropped', note: '' } }))}>Drop…</button>
            </div>
          </div>
        )}
        {t.status !== 'open' && !w && (
          <div className="tk-actions">
            <button type="button" className="quiet" onClick={() => setWhy((o) => ({ ...o, [t.task_id]: { status: 'open', note: '' } }))}>Open again…</button>
          </div>
        )}
        {w && (
          <div className="fields">
            <label className="wide">{w.status === 'dropped' ? 'Why drop it?' : 'Why open it again?'}
              <input autoFocus value={w.note} maxLength={300}
                onChange={(e) => setWhy((o) => ({ ...o, [t.task_id]: { ...w, note: e.target.value } }))} />
            </label>
            <div className="tk-actions">
              <button type="button" disabled={!w.note.trim()} onClick={() => decide(t)}>{w.status === 'dropped' ? 'Drop the task' : 'Open it again'}</button>
              <button type="button" className="quiet" onClick={() => setWhy((o) => ({ ...o, [t.task_id]: undefined }))}>Cancel</button>
            </div>
          </div>
        )}
        <div className="history">
          {t.history.map((h, i) => <span key={i}>{historyLine(h)}</span>)}
        </div>
      </div>
    )
  }

  return (
    <details className="card sec tasks-panel" open={expanded} onToggle={(e) => setExpanded(e.currentTarget.open)}>
      <summary>
        <span className="micro">Tasks · {open.length} open</span>
        <span className="note">{overdue ? `${overdue} overdue` : 'what is left to do in this case'}</span>
      </summary>
      <div className="body requests-panel">
        {open.map(row)}

        <div className="request-add">
          {!form && <button type="button" onClick={() => setForm(EMPTY)}>Add a task</button>}
        </div>

        {form && (
          <form className="tk-form" aria-label="Add a task" onSubmit={save}>
            <div className="fields">
              <label className="wide">What has to be done<input value={form.title} onChange={set('title')} maxLength={200} placeholder="e.g. Send the notice to the bank" /></label>
              <label>Assigned to<input value={form.assignee} onChange={set('assignee')} maxLength={120} placeholder="a name" /></label>
              <label>Due<input type="date" value={form.due_on} onChange={set('due_on')} /></label>
              <label className="wide">Notes<textarea rows={2} value={form.notes} onChange={set('notes')} /></label>
            </div>
            <div className="request-add">
              <button type="submit" className="tk-save" disabled={!form.title.trim()}>Add the task</button>
              <button type="button" className="quiet" onClick={() => setForm(null)}>Cancel</button>
            </div>
          </form>
        )}
        {error && <p className="error-line" role="alert">{error}</p>}

        {closed.length > 0 && (
          <details className="tk-closed">
            <summary><span className="note">Done and dropped · {closed.length}</span></summary>
            {closed.map(row)}
          </details>
        )}
        <p className="note">Kept with this browser&apos;s and unit&apos;s records. Nothing is deleted: dropping a task, or opening it again, asks why.</p>
      </div>
    </details>
  )
}
