import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchDueTasks } from '../api'
import { plain } from '../text'
import { dueText } from './case/TasksPanel'
import './TaskDeadlines.css'

/** The home page's list of open tasks due within a week or overdue, across
 * the officer's cases (backend GET /tasks/due). Shows nothing when none is,
 * or when the list cannot be reached. */
export default function TaskDeadlines() {
  const [due, setDue] = useState([])
  useEffect(() => { fetchDueTasks(7).then((d) => setDue(d.tasks ?? [])).catch(() => setDue([])) }, [])
  if (!due.length) return null
  return (
    <section className="card glass console-card task-deadlines" aria-labelledby="console-tasks">
      <div className="console-card-head"><h2 id="console-tasks">Tasks due</h2><span className="console-figure">{due.length}</span></div>
      <ul className="recent-cases">
        {due.map((t) => {
          const d = dueText(t)
          return (
            <li key={t.task_id}>
              <Link to={`/case/${t.case_id}?tab=evidence`}>
                <span className="td-title">{plain(t.title)}</span>
                {t.assignee && <span className="td-who">{plain(t.assignee)}</span>}
                <span className={`pill ${d.tone} td-when`}>{d.text}</span>
              </Link>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
