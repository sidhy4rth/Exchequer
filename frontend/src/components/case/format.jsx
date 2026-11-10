import { useEffect, useState } from 'react'

// How a case's views write addresses, amounts, times and transaction links,
// shared by the case page and the views that live in files of their own.

export const PATTERN_NAME = { peel_chain: 'Peel chain', amount_split: 'Amount split' }
export const RISK_NAME = { sanctioned: 'Sanctioned entity', seized: 'Seizure order', mixer: 'Mixer', frozen: 'Frozen by issuer', stolen: 'Stolen funds', reported: 'TronScan warning', gambling: 'Gambling platform', poisoning: 'Address poisoning', scam: 'Reported scam', laundering: 'Laundering' }

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

export const when = (seconds) =>
  seconds ? new Date(seconds * 1000).toISOString().slice(0, 16).replace('T', ' ') : ''
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

/** An address that copies itself when clicked and shows the full value on hover. */
export function Address({ value, head = 10, tail = 8, className = '' }) {
  const [copied, setCopied] = useState(false)
  // The mark clears itself, and its timer goes with the button: a timer left
  // running would set state on a page that is no longer there.
  useEffect(() => {
    if (!copied) return undefined
    const timer = setTimeout(() => setCopied(false), 1100)
    return () => clearTimeout(timer)
  }, [copied])
  const copy = () => {
    navigator.clipboard?.writeText(value).then(() => setCopied(true), () => {})
  }
  return (
    <button type="button" className={`addr ${copied ? 'copied' : ''} ${className}`} title={`${value} — click to copy`} onClick={copy}>
      {copied ? 'copied' : middle(value, head, tail)}
    </button>
  )
}
