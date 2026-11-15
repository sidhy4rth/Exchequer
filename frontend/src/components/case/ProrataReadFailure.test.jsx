import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ProrataReadFailure from './ProrataReadFailure'
import { READ_FAILURE_WORDING, readFailureSentence } from './readFailureWording'

const KINDS = ['rate_limit', 'no_answer', 'quota', 'stopped', 'bad_response', 'provider_error', 'error']

describe('the pro-rata read failure sentence', () => {
  it('has wording for every kind the backend sets', () => {
    expect(Object.keys(READ_FAILURE_WORDING).sort()).toEqual([...KINDS].sort())
  })

  it.each(KINDS)('says what stopped the check and to trace again: %s', (kind) => {
    const { container } = render(<ProrataReadFailure prorata={{ status: 'unknown', reason: 'r', read_failure: kind }} />)
    const p = container.querySelector('.prorata-read-failure')
    expect(p).toHaveTextContent('Amount not checked:')
    expect(p).toHaveTextContent(`The amount check could not be done: ${READ_FAILURE_WORDING[kind]}.`)
    expect(p).toHaveTextContent('Trace again later for a complete score.')
  })

  it('reads an unrecognised kind as an unexpected error', () => {
    expect(readFailureSentence({ status: 'unknown', read_failure: 'new_kind' })).toContain(READ_FAILURE_WORDING.error)
  })

  it('renders nothing when the field is absent', () => {
    const { container } = render(<ProrataReadFailure prorata={{ status: 'unknown', reason: 'too many transfers' }} />)
    expect(container).toBeEmptyDOMElement()
    expect(readFailureSentence(null)).toBeNull()
    expect(readFailureSentence(undefined)).toBeNull()
  })

  it.each(['estimated', 'not_applicable', undefined])('renders nothing when the status is %s', (status) => {
    const { container } = render(<ProrataReadFailure prorata={{ status, read_failure: 'rate_limit' }} />)
    expect(container).toBeEmptyDOMElement()
  })
})
