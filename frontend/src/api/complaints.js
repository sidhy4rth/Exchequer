// The officers' complaints queue: what citizens sent from their own site
// (backend/app/routes/complaints.py). Only an officer's message goes back.
import { BASE, apiFetch, jsonOrThrow } from './client'

const path = (reference, rest = '') => `${BASE}/complaints/${encodeURIComponent(reference)}${rest}`
const post = (url, body) => apiFetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

/** One page of the queue, newest first (one status, or all of them), and its total. */
export async function fetchComplaints(status = null, offset = 0) {
  const q = `limit=100${status ? `&status=${encodeURIComponent(status)}` : ''}${offset ? `&offset=${offset}` : ''}`
  return jsonOrThrow(await apiFetch(`${BASE}/complaints?${q}`))
}

export async function fetchComplaint(reference) {
  return jsonOrThrow(await apiFetch(path(reference)))
}

export async function setComplaintStatus(reference, status) {
  return jsonOrThrow(await post(path(reference, '/status'), { status }))
}

/** The officer's reply: the one thing the citizen reads back. */
export async function sendComplaintMessage(reference, body) {
  return jsonOrThrow(await post(path(reference, '/messages'), { body }))
}

export async function linkComplaintCase(reference, caseId) {
  return jsonOrThrow(await post(path(reference, '/link-case'), { case_id: caseId }))
}
