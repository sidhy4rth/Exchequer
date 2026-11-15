// Keccak-256, the hash EIP-55 address checksums are built on: a port of
// backend/app/keccak.py, so the browser holds an address to the same rule the
// server does. The original Keccak padding (0x01), not NIST SHA-3's (0x06).
// BigInt lanes keep it short; it is run once per mixed-case address found.

const MASK = (1n << 64n) - 1n
const RC = [
  0x0000000000000001n, 0x0000000000008082n, 0x800000000000808An, 0x8000000080008000n,
  0x000000000000808Bn, 0x0000000080000001n, 0x8000000080008081n, 0x8000000000008009n,
  0x000000000000008An, 0x0000000000000088n, 0x0000000080008009n, 0x000000008000000An,
  0x000000008000808Bn, 0x800000000000008Bn, 0x8000000000008089n, 0x8000000000008003n,
  0x8000000000008002n, 0x8000000000000080n, 0x000000000000800An, 0x800000008000000An,
  0x8000000080008081n, 0x8000000000008080n, 0x0000000080000001n, 0x8000000080008008n,
]
// Rotation offsets r[x][y].
const ROT = [
  [0, 36, 3, 41, 18],
  [1, 44, 10, 45, 2],
  [62, 6, 43, 15, 61],
  [28, 55, 25, 21, 56],
  [27, 20, 39, 8, 14],
]
const RATE = 136 // bytes: 1600 - 2 * 256 bits

const rotl = (v, s) => (s ? ((v << BigInt(s)) | (v >> BigInt(64 - s))) & MASK : v)

function permute(a) {
  for (const rc of RC) {
    const c = [0, 1, 2, 3, 4].map((x) => a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4])
    const d = [0, 1, 2, 3, 4].map((x) => c[(x + 4) % 5] ^ rotl(c[(x + 1) % 5], 1))
    for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) a[x][y] ^= d[x]
    const b = [0, 1, 2, 3, 4].map(() => [0n, 0n, 0n, 0n, 0n])
    for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) b[y][(2 * x + 3 * y) % 5] = rotl(a[x][y], ROT[x][y])
    for (let x = 0; x < 5; x++) {
      for (let y = 0; y < 5; y++) a[x][y] = b[x][y] ^ (~b[(x + 1) % 5][y] & b[(x + 2) % 5][y] & MASK)
    }
    a[0][0] ^= rc
  }
}

/** Keccak-256 of `data` (a Uint8Array) as 64 lower-case hex characters. */
export function keccak256Hex(data) {
  const state = [0, 1, 2, 3, 4].map(() => [0n, 0n, 0n, 0n, 0n])
  const length = data.length + 1 + ((RATE - ((data.length + 1) % RATE)) % RATE)
  const padded = new Uint8Array(length)
  padded.set(data)
  padded[data.length] = 0x01
  padded[length - 1] |= 0x80
  for (let start = 0; start < length; start += RATE) {
    for (let i = 0; i < RATE / 8; i++) {
      let lane = 0n
      for (let k = 7; k >= 0; k--) lane = (lane << 8n) | BigInt(padded[start + 8 * i + k])
      state[i % 5][Math.floor(i / 5)] ^= lane
    }
    permute(state)
  }
  let out = ''
  for (let i = 0; i < 4; i++) {
    let lane = state[i % 5][Math.floor(i / 5)]
    for (let k = 0; k < 8; k++) { out += Number(lane & 0xffn).toString(16).padStart(2, '0'); lane >>= 8n }
  }
  return out
}
