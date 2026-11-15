import { plain } from '../../text'
import { Address, num } from './format'
import './PrivacyNotes.css'

// The privacy protocols the funds passed through (Railgun, Aztec, Hinkal,
// Privacy Pools; flag EXCHEQUER_PRIVACY_CATEGORY, #189). A note, never a risk
// hit: grey and dotted, not the red alert, and it counts toward nothing. The
// trace never stopped at one, though a pool's payouts may not be followed.
// Renders nothing for a case without any.
export default function PrivacyNotes({ result, unit }) {
  const matches = result?.privacy_matches ?? []
  if (!matches.length) return null
  const notes = result.privacy_notes ?? []
  return (
    <section className="privacy-notes" aria-label="Privacy protocols on the route">
      <div className="title">
        {matches.length === 1 ? 'A privacy protocol' : `${matches.length} privacy protocols`} on the route · a note, not an accusation
      </div>
      <p className="lede">
        Funds passing through a privacy protocol lose their visible link, so what leaves it is not shown on chain to be
        the same money. Being a privacy protocol never stops the trace; each note says whether the contract&apos;s payouts
        were followed. No sanctions list or enforcement action names these protocols.
      </p>
      {matches.map((m, i) => (
        <div className="line" key={m.address}>
          <strong>{plain(m.entity)}</strong> — <Address value={m.address} />
          {' · '}{m.depth === 0 ? 'the reported address itself' : `${m.depth} hop${m.depth === 1 ? '' : 's'} away, ${num(m.value_received_native)} ${unit ?? ''} reached it`}
          {notes[i] && <p className="note">{notes[i]}</p>}
        </div>
      ))}
    </section>
  )
}
