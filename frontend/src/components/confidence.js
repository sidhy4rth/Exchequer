// How confidence and patterns are shown (R10, problems M4 and M5). Lane A.
//
// The score is a weighted sum of three inputs whose weights are judgement, not
// fitted to real outcomes (README, "The weights are judgement, not
// calibration"). Shown as "0.875" it reads like a measured probability, which
// it is not, so the interface leads with the band and keeps the number in the
// working.

// Mirrors BAND_THRESHOLDS in backend/app/scoring.py. A test pins the two together.
export const BAND_THRESHOLDS = [[0.75, 'high'], [0.5, 'moderate'], [0.25, 'low']]

export function bandOf(score) {
  if (score == null) return null
  for (const [threshold, name] of BAND_THRESHOLDS) if (score >= threshold) return name
  return 'very low'
}

/** "high" -> "High". */
export function bandLabel(band) {
  return band ? band.replace(/^./, (c) => c.toUpperCase()) : ''
}

export const BAND_RULE = 'High is a score of 0.75 or more, moderate 0.50, low 0.25. The weights are judgement, not fitted to real outcomes: read the band, not the decimal.'

// How often each pattern fired on real wallets, from README.md "Validation
// against real wallets": 32 documented fraud or theft wallets and 47 ordinary
// high-volume ones, traced at depth 3, current thresholds.
export const PATTERN_VALIDATION = {
  amount_split: { fraud: 6, fraudOf: 32, ordinary: 5, ordinaryOf: 47 },
  peel_chain: { fraud: 2, fraudOf: 32, ordinary: 2, ordinaryOf: 47 },
}

export function validationLine(pattern) {
  const v = PATTERN_VALIDATION[pattern]
  if (!v) return null
  return `Measured on real wallets, this shape appeared in ${v.fraud} of ${v.fraudOf} documented fraud wallets and ${v.ordinary} of ${v.ordinaryOf} ordinary ones, so on its own it does not tell them apart.`
}
