import { describe, expect, it } from 'vitest'
import { checkHash } from './hash.js'

const HEX = 'fde547813899a616a09c79842f0a413ac561505e0baa6db6b11f910a34a02e8e'
const EVM = ['Ethereum', 'BNB Smart Chain', 'Polygon', 'Arbitrum']

describe('checkHash', () => {
  it('accepts 64 hex characters, which could be Tron or an Ethereum-style network', () => {
    expect(checkHash(HEX)).toEqual({ ok: true, hash: HEX, networks: ['Tron', ...EVM] })
    expect(checkHash(HEX.toUpperCase())).toEqual({ ok: true, hash: HEX, networks: ['Tron', ...EVM] })
  })

  it('accepts a 0x prefix in either case, which puts Tron last but keeps it', () => {
    // Tron hashes are rarely written with 0x, but Exchequer accepts them either way.
    expect(checkHash(`0x${HEX}`)).toEqual({ ok: true, hash: `0x${HEX}`, networks: [...EVM, 'Tron'] })
    expect(checkHash(`0X${HEX.toUpperCase()}`)).toEqual({ ok: true, hash: `0x${HEX}`, networks: [...EVM, 'Tron'] })
  })

  it('ignores spaces, line breaks and invisible marks picked up while copying', () => {
    const messy = ` \n${HEX.slice(0, 30)}\n${HEX.slice(30, 50)}\u200B ${HEX.slice(50)}\t `
    expect(checkHash(messy)).toEqual({ ok: true, hash: HEX, networks: ['Tron', ...EVM] })
    expect(checkHash(`  0x${HEX}\r\n`)).toMatchObject({ ok: true, hash: `0x${HEX}` })
  })

  it.each(['200B', '200C', '200D', '200E', '200F', '202A', '202C', '202E', '2060', '2066', '2069', 'FEFF',
    '00A0', '00AD'])('ignores U+%s, which apps add when copying', (code) => {
    const mark = String.fromCodePoint(parseInt(code, 16))
    expect(checkHash(`${mark}${HEX}${mark}`)).toEqual({ ok: true, hash: HEX, networks: ['Tron', ...EVM] })
  })

  it('says when there is nothing to check', () => {
    for (const blank of ['', ' \n\t', '\u200B', '\u200E\u2066', undefined, null]) {
      expect(checkHash(blank)).toEqual({ ok: false, reason: 'empty' })
    }
  })

  it('counts the characters of a hash that is too short or too long, not counting 0x', () => {
    expect(checkHash(HEX.slice(1))).toEqual({ ok: false, reason: 'length', length: 63 })
    expect(checkHash(`${HEX}a`)).toEqual({ ok: false, reason: 'length', length: 65 })
    expect(checkHash(`0x${HEX.slice(2)}`)).toEqual({ ok: false, reason: 'length', length: 62 })
    expect(checkHash('412345678901')).toEqual({ ok: false, reason: 'length', length: 12 })
    expect(checkHash('0x')).toEqual({ ok: false, reason: 'length', length: 0 })
  })

  it('finds the one hash inside a link or a label pasted with it', () => {
    const inside = { ok: true, hash: HEX, networks: ['Tron', ...EVM], extracted: true }
    expect(checkHash(`https://tronscan.org/#/transaction/${HEX}`)).toEqual(inside)
    expect(checkHash(`TxID: ${HEX}`)).toEqual(inside)
    expect(checkHash(`TxID ${HEX}`)).toEqual(inside)
    expect(checkHash(`"${HEX.toUpperCase()}".`)).toEqual(inside)
    expect(checkHash(`Hash:\n${HEX.slice(0, 32)}\n${HEX.slice(32)}`)).toEqual(inside)
    expect(checkHash(`https://etherscan.io/tx/0x${HEX}`))
      .toEqual({ ok: true, hash: `0x${HEX}`, networks: [...EVM, 'Tron'], extracted: true })
  })

  it('refuses characters a hash never has', () => {
    expect(checkHash(`${HEX.slice(1)}g`)).toEqual({ ok: false, reason: 'chars' })
    expect(checkHash(`${HEX.slice(0, 32)}-${HEX.slice(32)}`)).toEqual({ ok: false, reason: 'chars' })
    expect(checkHash(`0x0x${HEX.slice(2)}`)).toEqual({ ok: false, reason: 'chars' })
    expect(checkHash('UPI ref 412345678901')).toEqual({ ok: false, reason: 'chars' })
    // Two different hashes: we cannot tell which one is the payment.
    expect(checkHash(`${HEX} / ${HEX.split('').reverse().join('')}`)).toEqual({ ok: false, reason: 'chars' })
    expect(checkHash(`TxID: ${HEX.slice(1)}`)).toEqual({ ok: false, reason: 'chars' })
  })

  it('recognises a wallet address pasted by mistake', () => {
    expect(checkHash('TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t')).toEqual({ ok: false, reason: 'address' })
    expect(checkHash(' 0xdAC17F958D2ee523a2206206994597C13D831ec7 ')).toEqual({ ok: false, reason: 'address' })
  })
})
