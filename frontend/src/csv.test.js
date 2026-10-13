import { describe, expect, it } from 'vitest'
import { complaintsFromCsv, parseCsv } from './csv'

describe('csv', () => {
  it('handles quotes, embedded commas and newlines, and CRLF', () => {
    expect(parseCsv('a,"b, c","d ""e"""\r\n1,"line\nbreak",3\n')).toEqual([
      ['a', 'b, c', 'd "e"'], ['1', 'line\nbreak', '3'],
    ])
  })

  it('maps forgiving header names to complaint fields', () => {
    const text = '﻿Acknowledgement No,Wallet Address,Network,Token\nNCRP-1,0xabc,bsc,USDT\n,,,\nNCRP-2,TXyz,tron,\n'
    expect(complaintsFromCsv(text)).toEqual([
      { reference: 'NCRP-1', address: '0xabc', chain: 'bsc', asset: 'USDT' },
      { reference: 'NCRP-2', address: 'TXyz', chain: 'tron' },
    ])
  })

  it('reads a headerless file as address[, chain]', () => {
    expect(complaintsFromCsv('0xabc,ethereum\n0xdef\n')).toEqual([
      { address: '0xabc', chain: 'ethereum' }, { address: '0xdef' },
    ])
  })
})
