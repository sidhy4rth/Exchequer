// A draft letter of request to a foreign country (backend letters_of_request.py,
// suite feature 7), from the case and the officer's details. The details go in
// the body, never the URL, and nothing typed is kept.
import { BASE, apiFetch, toError } from './client'

export async function draftLetterOfRequest(caseId, details) {
  const response = await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/letter-of-request`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(details),
  })
  if (!response.ok) throw await toError(response)
  return response.text()
}
