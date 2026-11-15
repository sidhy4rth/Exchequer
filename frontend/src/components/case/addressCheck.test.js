import { describe, expect, it } from 'vitest'
import { addressFamily, evmChecksumOk, isEvmAddress, isTronAddress } from './addressCheck'

// EIP-55 vectors as in backend/tests/test_address_checksum.py; Tron addresses
// from DEMO.md and backend/tests/fixtures/contract/exchange_wallet.json.
const EIP55 = [
  '0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed',
  '0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359',
  '0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB',
  '0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb',
  '0xdAC17F958D2ee523a2206206994597C13D831ec7',
]
const TRON = ['THWYhwUQnBcKpwSxaXjqv18RPtSoK4C5Ph', 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', 'TUVNGw2z3Gt8SDNukoj8GqSStKrve5i3ts']

describe('EVM addresses, as etherscan_client.py checks them', () => {
  it.each(EIP55)('passes the EIP-55 vector %s', (a) => {
    expect(evmChecksumOk(a)).toBe(true)
    expect(addressFamily(a)).toBe('evm')
  })

  it('fails one letter whose case was changed', () => {
    expect(evmChecksumOk('0x5AAeb6053F3E94C9b9A09f33669435E7Ef1BeAed')).toBe(false)
    expect(evmChecksumOk('0xDaC17F958D2ee523a2206206994597C13D831ec7')).toBe(false)
    expect(isEvmAddress('0x5AAeb6053F3E94C9b9A09f33669435E7Ef1BeAed')).toBe(false)
  })

  it('takes all-lower and all-upper, which carry no checksum', () => {
    expect(isEvmAddress('0x536c4921d1aafde6a5cda882fb5ca046f3601c65')).toBe(true)
    expect(isEvmAddress(`0x${EIP55[0].slice(2).toUpperCase()}`)).toBe(true)
  })

  it('refuses the wrong length or a non-hex character', () => {
    expect(isEvmAddress('0x536c4921d1aafde6a5cda882fb5ca046f3601c6')).toBe(false)
    expect(isEvmAddress('0x536c4921d1aafde6a5cda882fb5ca046f3601c655')).toBe(false)
    expect(isEvmAddress('0x536c4921d1aafde6a5cda882fb5ca046f3601c6g')).toBe(false)
  })
})

describe('Tron addresses, Base58Check', () => {
  it.each(TRON)('passes %s', (a) => {
    expect(isTronAddress(a)).toBe(true)
    expect(addressFamily(a)).toBe('tron')
  })

  it('fails one changed character (the checksum catches it)', () => {
    const typo = `${TRON[0].slice(0, 10)}${TRON[0][10] === 'c' ? 'd' : 'c'}${TRON[0].slice(11)}`
    expect(isTronAddress(typo)).toBe(false)
  })

  it('fails the wrong length, a character outside Base58, or another prefix', () => {
    expect(isTronAddress(TRON[0].slice(0, -1))).toBe(false)
    expect(isTronAddress(`${TRON[0]}x`)).toBe(false)
    expect(isTronAddress(`${TRON[0].slice(0, -1)}0`)).toBe(false)
    expect(isTronAddress(`A${TRON[0].slice(1)}`)).toBe(false)
    expect(addressFamily('hello')).toBe(null)
  })
})
