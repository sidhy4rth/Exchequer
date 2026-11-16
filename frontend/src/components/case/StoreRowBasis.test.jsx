import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import StoreRowBasis, { basisLines, storeBasis } from './StoreRowBasis'
import wording from '../../../../backend/tests/fixtures/store_basis_lines.json'

// The same file backend/tests/test_store_basis_wording.py checks report.basis_lines
// against: the screen and the report's FINDING say the same sentences.
const [own, deposit, unlabelled] = wording.cases
const CASE = '0x' + 'de90'.repeat(10)  // fixture address

function resultWith(basis, { exchange = 'ExampleX', address = CASE } = {}) {
  return {
    exchange, exchange_address: CASE,
    matches: [{ address: '0x' + 'c3'.repeat(20) }, { address, ...(basis === undefined ? {} : { attribution_basis: basis }) }],
  }
}

describe("the basis lines, in the report's words", () => {
  it.each(wording.cases.map((c) => [c.name, c]))('%s', (_, c) => {
    expect(basisLines(c.basis, c.exchange)).toEqual(c.lines)
  })
})

describe('a label-store row on the trace screen', () => {
  it("shows a deposit row's sweep and says it is an inference", () => {
    render(<StoreRowBasis result={resultWith(deposit.basis)} />)
    const group = screen.getByRole('group', { name: 'What this attribution stands on' })
    expect(group).toHaveTextContent("INFERRED from the exchange's own list and a sweep into it")
    expect(group).toHaveTextContent(deposit.lines[0])
    expect(group).toHaveTextContent(deposit.lines[1])
    expect(group).toHaveTextContent('This is an inference from public records, which only ExampleX can confirm.')
  })

  it('leaves out the label of a swept-to wallet the label file does not name', () => {
    render(<StoreRowBasis result={resultWith(unlabelled.basis)} />)
    expect(screen.getByRole('group')).toHaveTextContent(unlabelled.lines[1])
    expect(screen.getByRole('group')).not.toHaveTextContent('(ExampleX 1)')
  })

  it("shows an own-wallet row's list, and no sweep", () => {
    render(<StoreRowBasis result={resultWith(own.basis)} />)
    const group = screen.getByRole('group')
    expect(group).toHaveTextContent("the exchange's own published address list (PoR)")
    expect(group).toHaveTextContent(own.lines[0])
    expect(group).not.toHaveTextContent(/Sent funds|INFERRED/)
  })

  it('drops hidden characters from the list text, as the screen does for labels', () => {
    const basis = { ...own.basis, source: `por:example​:2026-11` }
    render(<StoreRowBasis result={resultWith(basis)} />)
    expect(screen.getByRole('group')).toHaveTextContent('Listed by ExampleX in its own published address list: por:example:2026-11.')
  })
})

describe('any other case renders nothing', () => {
  it.each([
    ['no attribution_basis on the match', resultWith(undefined)],
    ['a basis with no source', resultWith({ kind: 'x', source: '' })],
    ['a basis on a match the case does not name', resultWith(deposit.basis, { address: '0x' + 'c4'.repeat(20) })],
    ['no exchange reached', { ...resultWith(deposit.basis), exchange: null }],
    ['no matches at all', { exchange: 'ExampleX', exchange_address: CASE }],
    ['no result', null],
  ])('%s', (_, result) => {
    const { container } = render(<StoreRowBasis result={result} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('storeBasis is null without a basis', () => {
    expect(storeBasis(resultWith(undefined))).toBeNull()
    expect(storeBasis(resultWith(deposit.basis))).toBe(deposit.basis)
  })
})
