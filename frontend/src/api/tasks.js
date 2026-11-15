// A task list per case (backend tasks.py, suite feature 6): what still has to
// be done in a case, who it is assigned to, by when, and what came of it.
import { BASE, apiFetch, jsonOrThrow } from './client'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export async function fetchCaseTasks(caseId) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/tasks`))
}

export async function addTask(caseId, body) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/tasks`, {
    method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(body),
  }))
}

/** Change a task, close it (status done or dropped), open it again, or add a note. */
export async function updateTask(taskId, changes) {
  return jsonOrThrow(await apiFetch(`${BASE}/tasks/${encodeURIComponent(taskId)}`, {
    method: 'PATCH', headers: JSON_HEADERS, body: JSON.stringify(changes),
  }))
}

/** Open tasks due within `days` days or overdue, across the viewer's cases, most overdue first. */
export async function fetchDueTasks(days = 7) {
  return jsonOrThrow(await apiFetch(`${BASE}/tasks/due?days=${encodeURIComponent(days)}`))
}
