// What stopped the pro-rata amount check, when a provider read did (#320, #322).
// Mirrors READ_FAILURE_WORDING in backend/app/prorata.py: keep the two in step.

export const READ_FAILURE_WORDING = {
  rate_limit: 'the data provider did not answer (rate limit)',
  no_answer: 'the data provider did not answer (no response, or a server error)',
  quota: "the data provider's allowance is used up for now",
  stopped: 'the trace reached its own time or request limit first',
  bad_response: 'the data provider sent a response Exchequer could not read',
  provider_error: 'the data provider reported an error',
  error: 'an unexpected error stopped the read',
}

/** The sentence for a pro-rata estimate a failed read left unknown; null for
 * a complete estimate, one the path itself ruled out, or no pro-rata at all.
 * An unrecognised kind reads as "error", as on the backend. */
export function readFailureSentence(prorata) {
  const kind = prorata?.read_failure
  if (!kind || prorata.status !== 'unknown') return null
  const words = READ_FAILURE_WORDING[kind] ?? READ_FAILURE_WORDING.error
  return `The amount check could not be done: ${words}. Trace again later for a complete score.`
}
