// Whether a string is a well-formed address of a chain Exchequer traces, by the
// backend's own rules (etherscan_client.py: is_evm_address, evm_checksum_ok,
// is_tron_address), so what the export scan reports is what a trace would take.
// The server stays the authority: a trace started from a found address is
// checked there again.

import { keccak256Hex } from './keccak'
import { Sha256 } from './sha256'

export const EVM_ADDRESS = /^0x[0-9a-fA-F]{40}$/
export const TRON_ADDRESS = /^T[1-9A-HJ-NP-Za-km-z]{33}$/
const BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

/** True unless `address` mixes upper and lower case against its EIP-55
 * checksum. All-lower and all-upper carry no checksum and pass. */
export function evmChecksumOk(address) {
  const body = address.slice(2)
  if (body === body.toLowerCase() || body === body.toUpperCase()) return true
  const digest = keccak256Hex(new TextEncoder().encode(body.toLowerCase()))
  for (let i = 0; i < body.length; i++) {
    const ch = body[i]
    if (ch >= '0' && ch <= '9') continue
    if ((ch === ch.toUpperCase()) !== (parseInt(digest[i], 16) >= 8)) return false
  }
  return true
}

export const isEvmAddress = (address) => EVM_ADDRESS.test(address) && evmChecksumOk(address)

/** A Tron address in Base58Check form: 25 bytes, 0x41 first, the last four the
 * double SHA-256 of the rest. */
export function isTronAddress(address) {
  if (!TRON_ADDRESS.test(address)) return false
  let n = 0n
  for (const ch of address) n = n * 58n + BigInt(BASE58.indexOf(ch))
  if (n >= 1n << 200n) return false // more than 25 bytes
  const raw = new Uint8Array(25)
  for (let i = 24; i >= 0; i--) { raw[i] = Number(n & 0xffn); n >>= 8n }
  if (raw[0] !== 0x41) return false
  const once = new Sha256().update(raw.subarray(0, 21)).hex()
  const twice = new Sha256().update(Uint8Array.from(once.match(/../g), (h) => parseInt(h, 16))).hex()
  return twice.slice(0, 8) === [...raw.subarray(21)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

/** 'evm', 'tron' or null: the address family `text` is a valid address of. */
export function addressFamily(text) {
  if (isEvmAddress(text)) return 'evm'
  if (isTronAddress(text)) return 'tron'
  return null
}
