// The role a wallet plays on both maps, and the flag counts the Maps view
// shows above them. The same order as roleOf in GraphView and FlowView: the
// reported address first, then a confirmed risk-list hit, a gambling
// platform (an attribution, not a risk), a labelled exchange, an inferred
// deposit, a service contract, and only then a pattern that fired.

export function roleOf(node) {
  if (!node) return 'node'
  if (node.is_seed) return 'seed'
  if (node.risk_category === 'gambling') return 'gambling'
  if (node.risk_category) return 'risk'
  if (node.exchange && !node.inferred_exchange) return 'exchange'
  if (node.inferred_exchange) return 'inferred'
  if (node.is_router || node.is_service_contract) return 'service'
  if (node.flags?.length) return 'flagged'
  return 'node'
}

/** Whether a list confirms this wallet as a risk (sanctioned, seized, mixer,
 * frozen, stolen, scam...). A gambling platform is an attribution, not one. */
export const isConfirmedRisk = (node) => Boolean(node?.risk_category) && node.risk_category !== 'gambling'

/** How many wallets in `graph` a pattern flagged without a list confirming
 * them (possible), and how many a list confirms (confirmed). */
export function flagCounts(graph) {
  const nodes = graph?.nodes ?? []
  return {
    possible: nodes.filter((n) => roleOf(n) === 'flagged').length,
    confirmed: nodes.filter(isConfirmedRisk).length,
  }
}
