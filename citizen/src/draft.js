import { istField } from './api.js'

// The complaint pack's draft (Pack.jsx), kept in this tab's sessionStorage
// only. Reading or writing it never throws: blocked storage just keeps nothing.
export const KEY = 'exchequer-citizen-pack'

export function readDraft() {
  try { return JSON.parse(sessionStorage.getItem(KEY)) } catch { return null }
}

export function writeDraft(draft) {
  try {
    if (draft) sessionStorage.setItem(KEY, JSON.stringify(draft))
    else sessionStorage.removeItem(KEY)
  } catch { /* storage blocked */ }
}

const PACK_NETWORK = { Tron: 'Tron (TRC20)', Ethereum: 'Ethereum (ERC20)', 'BNB Smart Chain': 'BNB Smart Chain (BEP20)',
  Polygon: 'Polygon', Arbitrum: 'Arbitrum' }
const filled = (p) => p && typeof p === 'object' && Object.values(p).some((v) => typeof v === 'string' && v.trim())

/** Adds a payment found on the blockchain (C4) to the pack, once: the wallet paid is the one it went to. */
export function addToPack(found) {
  const draft = readDraft() ?? {}
  const payments = (Array.isArray(draft.payments) ? draft.payments : []).filter(filled)
  if (!payments.some((p) => p.hash === found.hash)) {
    payments.push({ hash: found.hash, amount: found.amount, token: found.token,
      network: PACK_NETWORK[found.network] ?? '', paidAt: istField(found.time), wallet: found.to })
  }
  writeDraft({ ...draft, payments })
}
