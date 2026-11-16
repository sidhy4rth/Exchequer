import { readFailureSentence } from './readFailureWording'
import './ProrataReadFailure.css'

// Shown under the pro-rata line when the amount check failed at a provider
// read, so the lower score reads as the read's doing, not the money's.
// Renders nothing otherwise.
export default function ProrataReadFailure({ prorata }) {
  const sentence = readFailureSentence(prorata)
  if (!sentence) return null
  return (
    <p className="note prorata-read-failure">
      <strong>Amount not checked:</strong> {sentence}
    </p>
  )
}
