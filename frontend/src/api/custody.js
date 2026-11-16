// Custody wallets (suite feature 9, backend custody.py and custody_log.py): the
// multisig wallets a case's seized crypto is held in, and the signing log of
// every deposit and release. Never a key: the server refuses one in any field.
import { BASE, apiFetch, jsonOrThrow } from './client'

const post = (body) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

/** The case's custody wallets, each with its movements; `enabled: false` when the server's flag is off. */
export async function fetchCaseCustody(caseId) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/custody`))
}

export async function addCustodyWallet(caseId, body) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/custody`, post(body)))
}

export async function proposeMovement(walletId, body) {
  return jsonOrThrow(await apiFetch(`${BASE}/custody/${encodeURIComponent(walletId)}/movements`, post(body)))
}

/** One step of a movement: approve ({ signer }), broadcast ({ tx_hash }), confirm, or cancel ({ reason }). */
export async function movementStep(movementId, step, body = {}) {
  return jsonOrThrow(await apiFetch(`${BASE}/custody/movements/${encodeURIComponent(movementId)}/${encodeURIComponent(step)}`, post(body)))
}

/** The newest custody balance check of the case; `enabled: false` when the server's flag is off. */
export async function fetchCustodyBalance(caseId) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/custody-balance`))
}

/** Read the case's custody addresses on chain now, against the asset register (custody_balance.py). */
export async function runCustodyBalance(caseId) {
  return jsonOrThrow(await apiFetch(`${BASE}/trace/${encodeURIComponent(caseId)}/custody-balance`, post({})))
}
