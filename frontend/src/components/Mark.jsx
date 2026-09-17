// The Exchequer mark: a chequer. The Exchequer was named for the chequered
// cloth on which the Crown's money was counted, square by square; one square
// is red -- the sum being traced. Drawn inline so it takes the current text
// colour and the red token, and reads at sixteen pixels.
export default function Mark({ size = 24, className = '' }) {
  const cells = []
  for (let i = 0; i < 4; i += 1) {
    for (let j = 0; j < 4; j += 1) {
      if ((i + j) % 2 === 0) {
        cells.push(<rect key={`${i}${j}`} x={j * 25} y={i * 25} width="25" height="25" fill={i === 2 && j === 2 ? 'var(--red)' : 'currentColor'} />)
      }
    }
  }
  return (
    <svg className={`mark ${className}`} width={size} height={size} viewBox="0 0 100 100" aria-hidden="true">
      <clipPath id="mark-clip"><rect width="100" height="100" rx="14" /></clipPath>
      <g clipPath="url(#mark-clip)">{cells}</g>
    </svg>
  )
}
