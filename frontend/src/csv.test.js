import { describe, expect, it } from 'vitest'
import { detectDelimiter, parseCsv, readComplaints } from './csv'

const VICTIM = '0x' + '11'.repeat(20)
const SUSPECT = '0x' + '22'.repeat(20)
const TRON = 'T' + 'A'.repeat(33)

describe('csv', () => {
  it('handles quotes, embedded commas and newlines, and CRLF', () => {
    expect(parseCsv('a,"b, c","d ""e"""\r\n1,"line\nbreak",3\n')).toEqual([
      ['a', 'b, c', 'd "e"'], ['1', 'line\nbreak', '3'],
    ])
  })

  it('maps forgiving header names to complaint fields', () => {
    const text = `﻿Acknowledgement No,Wallet Address,Network,Token\nNCRP-1,${SUSPECT},bsc,USDT\n,,,\nNCRP-2,${TRON},tron,\n`
    const { rows, errors } = readComplaints(text)
    expect(errors).toEqual([])
    expect(rows).toEqual([
      { line: 2, reference: 'NCRP-1', address: SUSPECT, chain: 'bsc', asset: 'USDT' },
      { line: 4, reference: 'NCRP-2', address: TRON, chain: 'tron' },
    ])
  })

  it('reads a headerless file as address[, chain]', () => {
    expect(readComplaints(`${SUSPECT},ethereum\n${VICTIM},bsc\n`).rows).toEqual([
      { line: 1, address: SUSPECT, chain: 'ethereum' }, { line: 2, address: VICTIM, chain: 'bsc' },
    ])
  })
})

describe('one delimiter per file (3-0)', () => {
  const HEAD = 'Acknowledgement No,Victim wallet,Wallet Address'

  it("keeps a ';' in the reference of a comma file inside its cell", () => {
    const { rows, errors } = readComplaints(`${HEAD}\n31911250012345; PS Cyber Blr,${VICTIM},${SUSPECT}\n`)
    expect(errors).toEqual([])
    expect(rows).toEqual([{ line: 2, reference: '31911250012345; PS Cyber Blr', address: SUSPECT }])
  })

  it('keeps a tab in the reference inside its cell', () => {
    const { rows } = readComplaints(`${HEAD}\n31911250012345\tPS Cyber Blr,${VICTIM},${SUSPECT}\n`)
    expect(rows[0].address).toBe(SUSPECT)
    expect(rows[0].reference).toBe('31911250012345\tPS Cyber Blr')
  })

  it("reads '1,5' in a semicolon file as one cell", () => {
    const { rows, delimiter } = readComplaints(`Ack No;Amount;Victim wallet;Suspect address\nA-1;1,5;${VICTIM};${SUSPECT}\n`)
    expect(delimiter).toBe(';')
    expect(rows).toEqual([{ line: 2, reference: 'A-1', address: SUSPECT }])
  })

  it('opens a quoted cell after a space', () => {
    const { rows, errors } = readComplaints(`Ack No,Note,Victim wallet,Suspect address\nA-5, "FIR 4, PS Whitefield",${VICTIM},${SUSPECT}\n`)
    expect(errors).toEqual([])
    expect(rows[0].address).toBe(SUSPECT)
  })

  it('refuses a row wider than the header, by its line, and sends no row for it', () => {
    const text = `${HEAD}\nA-1,${VICTIM},${SUSPECT}\nA-2,PS Cyber, Blr,${VICTIM},${SUSPECT}\n`
    const { rows, errors } = readComplaints(text)
    expect(rows.map((r) => r.line)).toEqual([2])
    expect(errors).toHaveLength(1)
    expect(errors[0].line).toBe(3)
    expect(errors[0].error).toMatch(/has 5 cells; the header has 3/)
  })

  it('refuses a row narrower than the header', () => {
    const { errors } = readComplaints(`${HEAD}\nA-1,${SUSPECT}\n`)
    expect(errors[0]).toMatchObject({ line: 2 })
    expect(errors[0].error).toMatch(/has 2 cells; the header has 3/)
  })

  it("honours Excel's sep= line", () => {
    expect(detectDelimiter('sep=;\na,b;c\n')).toBe(';')
    const { rows } = readComplaints(`sep=;\nreference;suspect address\nA, 1;${SUSPECT}\n`)
    expect(rows).toEqual([{ line: 3, reference: 'A, 1', address: SUSPECT }])
  })

  it('picks the most common separator on the first line, a comma on a tie', () => {
    expect(detectDelimiter('a;b;c,d\n')).toBe(';')
    expect(detectDelimiter('a\tb\tc\n')).toBe('\t')
    expect(detectDelimiter('a;b,c\n')).toBe(',')
    expect(detectDelimiter('"a;b;c",d\n')).toBe(',')
  })

  it('numbers rows by file line across a quoted line break, and refuses a quote never closed', () => {
    const text = `reference,suspect address\n"A-1\nsecond line",${SUSPECT}\nA-2,${VICTIM}\n"A-3,${SUSPECT}\n`
    const { rows, errors } = readComplaints(text)
    expect(rows.map((r) => [r.line, r.reference])).toEqual([[2, 'A-1\nsecond line'], [4, 'A-2']])
    expect(errors).toEqual([{ line: 5, error: 'opens a quote (") that is never closed.' }])
  })

  it('says when a row has no address', () => {
    const { rows, errors } = readComplaints(`reference,suspect address\nA-1,\n`)
    expect(rows).toEqual([])
    expect(errors).toEqual([{ line: 2, error: 'has no address.' }])
  })
})

describe('which column is the address (3-1)', () => {
  it("prefers 'suspect address' over a generic 'wallet'", () => {
    const { rows, columns } = readComplaints(`complaint no,wallet,suspect address,network\nNCRP-5,${VICTIM},${SUSPECT},ethereum\n`)
    expect(rows).toEqual([{ line: 2, reference: 'NCRP-5', address: SUSPECT, chain: 'ethereum' }])
    expect(columns.mapped.find((c) => c.field === 'address')).toEqual({ field: 'address', header: 'suspect address', column: 3 })
    expect(columns.unused).toEqual([{ header: 'wallet', column: 2 }])
  })

  it('refuses two columns of the same name', () => {
    const { rows, errors } = readComplaints(`reference,address,address\nA,${VICTIM},${SUSPECT}\n`)
    expect(rows).toEqual([])
    expect(errors[0].line).toBe(1)
    expect(errors[0].error).toMatch(/Two columns could be the suspect's address: 'address' \(column 2\) and 'address' \(column 3\)/)
  })

  it("takes 'Suspect Wallet Address' over 'Wallet Address'", () => {
    const { rows } = readComplaints(`Ack No,Wallet Address,Suspect Wallet Address,Network\nA,${VICTIM},${SUSPECT},ethereum\n`)
    expect(rows[0].address).toBe(SUSPECT)
  })

  it('never takes a victim column, whatever it is called', () => {
    const { rows } = readComplaints(`Victim Wallet,Fraudster wallet\n${VICTIM},${SUSPECT}\n`)
    expect(rows).toEqual([{ line: 2, address: SUSPECT }])
  })

  it('refuses two generic address columns, naming both', () => {
    const { errors } = readComplaints(`Wallet,Crypto Address\n${VICTIM},${SUSPECT}\n`)
    expect(errors[0].error).toMatch(/'Wallet' \(column 1\) and 'Crypto Address' \(column 2\)/)
    expect(errors[0].error).toMatch(/Rename the suspect's column to 'suspect address'/)
  })

  it('refuses a header with no address column instead of reading it as data', () => {
    const { rows, errors } = readComplaints(`Ack No,Victim wallet,Notes\nA,${VICTIM},x\n`)
    expect(rows).toEqual([])
    expect(errors).toEqual([{ line: 1, error: "has no address column. Name the suspect's column 'suspect address'." }])
  })

  it('refuses two columns of the same name for another field', () => {
    const { errors } = readComplaints(`suspect address,chain,chain\n${SUSPECT},ethereum,bsc\n`)
    expect(errors[0].error).toMatch(/Two columns are named 'chain' \(columns 2 and 3\)/)
  })
})
