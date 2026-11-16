import { plainSentence } from '../../text'
import './StoreRowBasis.css'

// What the attribution stands on when the case's address came from a
// label-store exchange row (ADR-0011, ADR-0012; flag EXCHEQUER_STORE_EXCHANGE_ROWS):
// the exchange's own published list, and for a deposit row the sweep that makes
// it a probable deposit address. Reads `matches[].attribution_basis` of the
// match the case names, as backend/app/report.py's store_basis does, and says it
// in the words of report.basis_lines, so the screen, the report's FINDING and
// the exchange letter say the same thing. Renders nothing for any other case.
export function storeBasis(result) {
  const address = result?.exchange_address
  const match = (result?.matches ?? []).find((m) => m.address === address)
  const basis = match?.attribution_basis
  return basis && typeof basis === 'object' && basis.source ? basis : null
}

export function basisLines(basis, exchange) {
  const lines = [`Listed by ${exchange} in its own published address list: ${basis.source}.`]
  const deposit = basis.deposit
  if (deposit && Object.keys(deposit).length) {
    const into = deposit.sweeps_to_label ? ` (${deposit.sweeps_to_label})` : ''
    lines.push(`Sent funds to ${deposit.sweeps_to}${into}, a wallet labelled as ${exchange}'s, `
      + `in tx ${deposit.sweep_tx} (checked ${deposit.checked_on}): the pattern of `
      + 'an exchange sweeping a customer deposit address. This is an inference from public '
      + `records, which only ${exchange} can confirm.`)
  }
  return lines
}

export default function StoreRowBasis({ result }) {
  const basis = storeBasis(result)
  if (!basis || !result.exchange) return null
  const deposit = basis.deposit && Object.keys(basis.deposit).length
  return (
    <div className="store-basis" role="group" aria-label="What this attribution stands on">
      <span className="micro">Basis</span>
      <p className="store-basis-kind">
        {deposit ? 'INFERRED from the exchange\'s own list and a sweep into it'
          : 'the exchange\'s own published address list (PoR)'}
      </p>
      {basisLines(basis, result.exchange).map((line) => <p key={line}>{plainSentence(line)}</p>)}
    </div>
  )
}
