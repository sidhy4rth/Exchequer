// The Timeline tab's stat cards (pack 2-glass-05), worked from the case's own
// data. Each function returns null when its data is missing or cannot carry
// the claim, and the card is then left out. A share is cut, never rounded up;
// a "within" span is rounded up, so the claim stays true; an elapsed span is
// cut to the minute.
import { plain } from '../../text'

const HOUR = 3600
const DAY = 86400
// What a freeze's text says, for a case stored before frozen_on.
const FREEZE_DAY = / on (\d{4}-\d{2}-\d{2})\b/
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

const sum = (rows) => rows.reduce((total, r) => total + (r.amount || 0), 0)
const byTime = (a, b) => a.time - b.time

/** A share as a percentage with one decimal, cut, never rounded up. */
export function shareText(share) {
  if (!(share > 0)) return '0%'
  const tenths = Math.floor(share * 1000 + 1e-9) / 10
  return tenths >= 0.1 ? `${tenths}%` : 'under 0.1%'
}

/** An elapsed span, cut to its smaller unit: "3 h 26 m", "59 m", "1 d 2 h". */
export function spanText(seconds) {
  const s = Math.max(0, Math.floor(seconds))
  const d = Math.floor(s / DAY)
  const h = Math.floor((s % DAY) / HOUR)
  const m = Math.floor((s % HOUR) / 60)
  if (d) return `${d} d ${h} h`
  return h ? `${h} h ${m} m` : `${m} m`
}

/** The reported wallet's own statement rows, when the trace went forward. */
function statementOf(result) {
  const st = result.statement
  if (!st || result.direction === 'incoming') return null
  const credits = (st.credits ?? []).filter((r) => !r.lookalike && !r.before_window && r.time)
  const debits = (st.debits ?? []).filter((r) => r.time)
  return { cap: st.rows_per_side, credits, debits, full: (st.credits ?? []).length, fullOut: (st.debits ?? []).length }
}

/** When the victim's money reached the reported wallet: a payment trace's
 * first payment; otherwise the largest credit at or before the first debit. */
export function arrival(result) {
  if (result.intake?.mode === 'payment') {
    const times = (result.intake.payments ?? []).map((p) => p.timestamp).filter(Boolean)
    return times.length ? Math.min(...times) : null
  }
  const st = statementOf(result)
  if (!st?.debits.length) return null
  const firstOut = Math.min(...st.debits.map((d) => d.time))
  const before = st.credits.filter((c) => c.time <= firstOut)
  if (!before.length) return null
  return before.reduce((big, c) => (c.amount > big.amount ? c : big)).time
}

/** "69.6% left the wallet within 45 h": of all that left after the money came
 * in, how much had gone once more than half of it had. Needs every debit, so
 * none when that side of the statement hit its row limit. */
export function leftWithin(result) {
  const st = statementOf(result)
  const start = st && arrival(result)
  if (start == null || !(st.cap > st.fullOut)) return null
  const out = st.debits.filter((d) => d.time >= start).sort(byTime)
  const total = sum(out)
  if (!(total > 0)) return null
  let sent = 0
  for (const d of out) {
    sent += d.amount || 0
    if (sent > total / 2) {
      const hours = Math.max(1, Math.ceil((d.time - start) / HOUR))
      const span = hours < 72 ? `${hours} h` : `${Math.ceil(hours / 24)} days`
      return { share: sent / total, value: shareText(sent / total), caption: `left the wallet within ${span}` }
    }
  }
  return null
}

/** "3 h 26 m from hop 1 to Binance": from the first transfer into hop 1 to the
 * first transfer into the exchange after it, hop by hop along the route. */
export function hopToExchange(result) {
  const path = (result.trace_path ?? []).map((step) => step.address)
  if (result.direction === 'incoming' || !result.exchange || path.length < 3) return null
  const transfers = result.transfers ?? []
  let first = null
  let at = null
  for (let i = 0; i < path.length - 1; i += 1) {
    const times = transfers
      .filter((t) => t.from === path[i] && t.to === path[i + 1] && t.timestamp && (at == null || t.timestamp >= at))
      .map((t) => t.timestamp)
    if (!times.length) return null
    at = Math.min(...times)
    if (first == null) first = at
  }
  const seconds = at - first
  return { seconds, value: spanText(seconds), caption: `from hop 1 to ${plain(result.exchange) || 'the exchange'}` }
}

/** "10 days until the wallet was empty": from the money arriving to the last
 * debit, rounded up, claimed only when neither statement side hit its row
 * limit and what came in has all gone out. */
export function emptyIn(result) {
  const st = statementOf(result)
  const start = st && arrival(result)
  if (start == null || !(st.cap > st.full) || !(st.cap > st.fullOut)) return null
  const came = sum(st.credits)
  const last = Math.max(...st.debits.map((d) => d.time))
  if (!(came > 0) || last < start || came - sum(st.debits) > came * 0.001) return null
  const days = Math.max(1, Math.ceil((last - start) / DAY))
  return { days, value: `${days} day${days === 1 ? '' : 's'}`, caption: 'until the wallet was empty' }
}

// Month names spelled out here: some browsers write September "Sept".
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const PARTS = Object.fromEntries(['Asia/Kolkata', 'UTC'].map((timeZone) => [timeZone, new Intl.DateTimeFormat('en-GB', {
  year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone,
})]))

/** Epoch seconds as they were in India (or UTC): {day: "19 Dec 2024", short:
 * "19 Dec", time: "14:36"}, by Intl in Asia/Kolkata. */
export function clock(seconds, timeZone = 'Asia/Kolkata') {
  const p = Object.fromEntries(PARTS[timeZone].formatToParts(new Date(seconds * 1000)).map((x) => [x.type, x.value]))
  const short = `${Number(p.day)} ${MONTHS[p.month - 1]}`
  return { day: `${short} ${p.year}`, short, time: `${p.hour}:${p.minute}` }
}

const dayText = (iso) => clock(Date.parse(`${iso}T00:00:00Z`) / 1000, 'UTC').day

/** "11 Sep 2026 · Tether froze both wallets": the first freeze day, from
 * risk_matches[].frozen_on, or the label's own words for an older case. */
export function frozeOn(result) {
  const frozen = (result.risk_matches ?? []).filter((m) => m.category === 'frozen')
  const dated = frozen
    .map((m) => ({ m, on: m.frozen_on ?? FREEZE_DAY.exec(m.label ?? '')?.[1] }))
    .filter((x) => ISO_DAY.test(x.on ?? ''))
  if (!dated.length) return null
  const days = [...new Set(dated.map((x) => x.on))].sort()
  const issuers = [...new Set(dated.map((x) => plain(x.m.issuer) || 'The issuer'))]
  // Count every frozen wallet, so one with no day never reads as "both".
  const n = dated.length
  const what = n < frozen.length ? `${n} of ${frozen.length} wallets` : n === 2 ? 'both wallets' : `${n} wallet${n === 1 ? '' : 's'}`
  return { on: days[0], value: dayText(days[0]), caption: `${issuers.join(' and ')} froze ${what}${days.length > 1 ? ', the first that day' : ''}` }
}

/** The cards to draw, in the pack's order; any without data is left out. */
export function timelineStats(result) {
  return [
    ['left', leftWithin, ''], ['exchange', hopToExchange, 'go'], ['empty', emptyIn, ''], ['frozen', frozeOn, 'risk'],
  ].flatMap(([key, work, tone]) => {
    const card = work(result)
    return card ? [{ key, tone, ...card }] : []
  })
}
