// Scanning a phone or computer export for what a crypto case needs (suite
// feature 2): wallet addresses of the chains Exchequer traces, transaction
// hashes, and runs of BIP-39 words shaped like a seed phrase. Any text export
// will do (CSV, TSV, XML, JSON, HTML, plain text): the scan reads it as text,
// a piece at a time, in this browser. Nothing in the file is sent anywhere.
//
// A seed phrase is reported by where it is and how many words it has, never by
// its words: the scanner counts list words in a row and keeps only that count
// and the line it started on. The rule is assets.py::_seed_phrase's: twelve or
// more list words in a row, numbers between them ignored (seed backups are
// often numbered), any other word or value ending the run.

import { addressFamily } from './addressCheck'
import { BIP39 } from './bip39English'

export const SEED_WORDS = 12
const TOKEN = /[0-9A-Za-z]+/g
const ALNUM = /[0-9A-Za-z]/
const HEX = /^[0-9a-fA-F]+$/
const DIGITS = /^[0-9]+$/
const LETTERS = /^[A-Za-z]+$/
// A run of letters and digits this long is no address or hash: it is dropped
// rather than held, so one huge base64 blob cannot fill the memory.
const LONGEST = 1 << 20
const CHUNK = 1024 * 1024
const LINES_KEPT = 5 // line numbers kept per value; the count is always whole

/** Holds what was found so far. push() takes the text in pieces of any size
 * (a value cut in two is joined again); finish() gives the result. */
export class ExportScanner {
  constructor({ words = BIP39, most = 5000 } = {}) {
    this.words = words
    this.most = most // distinct addresses and hashes kept; the rest are counted only
    this.line = 1
    this.bytes = 0
    this.endsWithBreak = false
    this.seen = false // any text at all
    this.carry = ''
    this.glued = false // the next piece starts inside a value that was dropped
    this.addresses = new Map()
    this.hashes = new Map()
    this.seeds = []
    this.run = 0
    this.runLine = 0
    this.runEnd = 0
    this.dropped = 0
  }

  push(text) {
    if (!text) return
    this.seen = true
    const all = this.carry + text
    let cut = all.length - 1
    while (cut >= 0 && ALNUM.test(all[cut])) cut -= 1
    if (cut < 0) {
      this.carry = all
      if (this.carry.length > LONGEST) { this.carry = ''; this.endRun(); this.glued = true }
      return
    }
    this.carry = all.slice(cut + 1)
    this.segment(all.slice(0, cut + 1))
  }

  segment(text) {
    let at = 0
    TOKEN.lastIndex = 0
    for (let m = TOKEN.exec(text); m; m = TOKEN.exec(text)) {
      this.lines(text, at, m.index)
      at = m.index + m[0].length
      if (this.glued && m.index === 0) { this.glued = false; this.endRun(); continue }
      this.glued = false
      this.token(m[0])
    }
    this.glued = false
    this.lines(text, at, text.length)
    this.endsWithBreak = text[text.length - 1] === '\n'
  }

  lines(text, from, to) {
    for (let i = from; i < to; i++) if (text.charCodeAt(i) === 10) this.line += 1
  }

  token(tok) {
    const n = tok.length
    if ((n === 42 || n === 34) && (tok.startsWith('0x') || tok[0] === 'T')) {
      const family = addressFamily(tok)
      if (family) { this.endRun(); this.keep(this.addresses, family === 'evm' ? tok.toLowerCase() : tok, tok, family); return }
    }
    if ((n === 66 && tok.startsWith('0x') && HEX.test(tok.slice(2))) || (n === 64 && HEX.test(tok))) {
      this.endRun()
      this.keep(this.hashes, tok.toLowerCase(), tok.toLowerCase(), n === 66 ? 'hex0x' : 'hex')
      return
    }
    if (DIGITS.test(tok)) return
    if (LETTERS.test(tok) && this.words.has(tok.toLowerCase())) {
      if (this.run === 0) this.runLine = this.line
      this.run += 1
      this.runEnd = this.line
      return
    }
    this.endRun()
  }

  keep(found, key, value, kind) {
    const had = found.get(key)
    if (had) {
      had.count += 1
      if (had.lines.length < LINES_KEPT && had.lines[had.lines.length - 1] !== this.line) had.lines.push(this.line)
    } else if (this.addresses.size + this.hashes.size < this.most) {
      found.set(key, { value, kind, count: 1, lines: [this.line] })
    } else this.dropped += 1
  }

  endRun() {
    if (this.run >= SEED_WORDS) this.seeds.push({ line: this.runLine, endLine: this.runEnd, words: this.run })
    this.run = 0
  }

  /** { lines, bytes, addresses, hashes, seeds, dropped }; addresses and hashes
   * in the order they first appear. A seed is { line, endLine, words }: a count. */
  finish() {
    const tail = this.carry
    this.carry = ''
    if (tail) this.segment(tail)
    this.endRun()
    const lines = !this.seen ? 0 : this.line - (this.endsWithBreak ? 1 : 0)
    return {
      lines, bytes: this.bytes, dropped: this.dropped, seeds: this.seeds,
      addresses: [...this.addresses.values()], hashes: [...this.hashes.values()],
    }
  }
}

async function bytesOf(blob) {
  if (typeof blob.arrayBuffer === 'function') return new Uint8Array(await blob.arrayBuffer())
  return new Uint8Array(await new Response(blob).arrayBuffer())
}

/** How the file's text is encoded, from its first bytes: a byte-order mark
 * says so; without one it is read as UTF-8. `binary` when it holds many NUL
 * bytes and no mark, which no text export does. */
export function encodingOf(head) {
  if (head[0] === 0xff && head[1] === 0xfe) return { encoding: 'utf-16le', binary: false }
  if (head[0] === 0xfe && head[1] === 0xff) return { encoding: 'utf-16be', binary: false }
  let nul = 0
  for (const b of head) if (b === 0) nul += 1
  return { encoding: 'utf-8', binary: head.length > 0 && nul / head.length > 0.1 }
}

const breathe = () => new Promise((resolve) => { setTimeout(resolve, 0) })

/** Scan a File or Blob, `chunk` bytes at a time, handing the page back
 * between pieces so it never freezes. `onProgress(0..1)` after each piece; an
 * aborted `signal` stops it. Gives finish()'s result plus { binary }. */
export async function scanFile(file, { onProgress, signal, chunk = CHUNK, words } = {}) {
  const scanner = new ExportScanner(words ? { words } : {})
  const head = await bytesOf(file.slice(0, 4096))
  const { encoding, binary } = encodingOf(head)
  const decoder = new TextDecoder(encoding)
  for (let at = 0; at < file.size; at += chunk) {
    if (signal?.aborted) throw new DOMException('Stopped', 'AbortError')
    const bytes = await bytesOf(file.slice(at, at + chunk))
    scanner.bytes += bytes.length
    scanner.push(decoder.decode(bytes, { stream: true }))
    onProgress?.(Math.min(1, (at + chunk) / file.size))
    await breathe()
  }
  scanner.push(decoder.decode())
  return { ...scanner.finish(), binary }
}
