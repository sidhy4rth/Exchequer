// OSINT tied to a case (suite feature 4): what the victim reported besides the
// wallet -- a scam domain, a Telegram username, a phone number, a UPI ID.
import { BASE, apiFetch, jsonOrThrow } from './client'

export async function fetchCaseIdentifiers(caseId) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/identifiers`))
}

export async function addIdentifier(caseId, body) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/identifiers`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))
}

export async function updateIdentifier(identifierId, changes) {
  return jsonOrThrow(await apiFetch(`${BASE}/identifiers/${encodeURIComponent(identifierId)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
  }))
}
