// What the console's search box understands, from the shape of the text
// alone, and where it sends each kind. The address and hash rules are the
// trace form's (and the backend's, which stays the authority): Ethereum and
// the other EVM chains share 0x and 40 hex characters; Tron is case-sensitive
// Base58 beginning with T. A payment's transaction hash is 0x and 64 hex on
// EVM chains; Tron's are 64 hex, often pasted with a 0x the explorer does not
// show.
export const ADDRESS_RE = {
  evm: /^0x[0-9a-fA-F]{40}$/,
  tron: /^T[1-9A-HJ-NP-Za-km-z]{33}$/,
}
export const HASH_RE = { evm: /^0x[0-9a-fA-F]{64}$/, tron: /^(0x)?[0-9a-fA-F]{64}$/ }
// A stored case's id (models.new_case_id: a UUID).
const CASE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Where the search box sends `text`, or null when it is none of these.
 * `health` is GET /chains as the shell loaded it (null until it answers).
 *
 * A wallet opens its trace link, which shows what it would run and waits for
 * a click: a search never starts a trace. Its chain is the site's default
 * when that reads the wallet's format, else the first such chain. On Tron
 * the money in a complaint is almost always USDT, so a Tron wallet asks for
 * USDT where the chain lists it. A transaction hash fills the new-trace form,
 * which still needs the wallet the victim paid; one without 0x can only be
 * Tron's, so the form starts on Tron. */
export function findTarget(text, health) {
  const q = (text ?? '').trim()
  const family = ADDRESS_RE.evm.test(q) ? 'evm' : ADDRESS_RE.tron.test(q) ? 'tron' : null
  if (family) {
    const fits = Object.values(health?.chains ?? {}).filter((c) => (c.address_family ?? 'evm') === family)
    const chain = fits.find((c) => c.key === health?.default_chain) ?? fits[0]
    const symbols = (chain?.assets ?? []).map((a) => a.symbol)
    const asset = family === 'tron' && (symbols.includes('USDT') || !chain) ? 'USDT' : symbols[0] ?? 'ETH'
    return `/trace/${q}?${new URLSearchParams({ chain: chain?.key ?? (family === 'tron' ? 'tron' : 'ethereum'), asset })}`
  }
  if (HASH_RE.tron.test(q)) return `/trace/new?${new URLSearchParams({ pay: q, ...(!q.startsWith('0x') && { chain: 'tron' }) })}`
  if (CASE_ID.test(q)) return `/case/${q.toLowerCase()}`
  return null
}
