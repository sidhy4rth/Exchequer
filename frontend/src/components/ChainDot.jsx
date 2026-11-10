// Each chain's own colour, for its dot and bar only: never for text or risk.
const CHAIN_TOKEN = { tron: 'tron', ethereum: 'eth', arbitrum: 'arb', polygon: 'poly', bsc: 'bnb' }
export const chainColour = (key) => `var(--c-${CHAIN_TOKEN[key] ?? 'eth'})`

export default function ChainDot({ chain }) {
  return <i className="chain-dot" style={{ background: chainColour(chain) }} aria-hidden="true" />
}
