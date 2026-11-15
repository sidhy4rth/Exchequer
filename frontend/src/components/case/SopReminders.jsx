import './SopReminders.css'

// Reminders from the MHA SOP for NCRP-CFCFRMS on a bank hold in the asset
// register (backend sop_reminders.py, behind EXCHEQUER_SOP_DEADLINES; the rows
// carry no `sop_reminders` when it is off). Each line quotes the SOP word for
// word with its section and copy. They are reminders, never deadlines
// Exchequer enforces: the register's own 45-day court deadline is unchanged.

const day = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

export default function SopReminders({ reminders }) {
  if (!reminders?.length) return null
  return (
    <details className="sop-reminders">
      <summary>SOP reminders, if this hold went through CFCFRMS · {reminders.length}</summary>
      <p className="note">{reminders[0].note}</p>
      <ul>
        {reminders.map((r) => (
          <li key={r.id}>
            {r.date && <span className="sop-date">{r.date_label}: {day(r.date)}. </span>}
            {r.hint} <a href={r.source_url} target="_blank" rel="noreferrer">Source, PDF page {r.page}</a>
          </li>
        ))}
      </ul>
    </details>
  )
}
