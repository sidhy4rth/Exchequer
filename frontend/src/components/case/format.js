// How the case views write addresses, amounts, times and transaction links.

/** Middle-truncated address: both ends carry identity, the middle does not. */
export function middle(address, head = 10, tail = 8) {
  if (!address || address.length <= head + tail + 1) return address
  return `${address.slice(0, head)}…${address.slice(-tail)}`
}

/** A transaction's page on the chain's explorer (Tronscan's is under #/). */
export function txUrl(explorer, chain, hash) {
  if (!explorer || !hash) return null
  return chain === 'tron' ? `${explorer}/#/transaction/${hash.replace(/^0x/, '')}` : `${explorer}/tx/${hash}`
}

export const mmss = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`

export const num = (value) =>
  value >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
                : Number((value || 0).toFixed(6)).toString()

const IST = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'Asia/Kolkata',
})
/** A moment as it was in India, "19 Dec 2024 14:36", from epoch seconds or an ISO string. */
export function ist(at) {
  if (at == null || at === '') return ''
  const date = new Date(typeof at === 'number' ? at * 1000 : at)
  return Number.isNaN(date.getTime()) ? '' : IST.format(date).replace(',', '')
}
