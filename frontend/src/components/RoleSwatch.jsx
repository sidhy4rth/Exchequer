// A map key's swatch, drawn the way both maps draw that role. Colour alone
// never tells roles apart, so the key carries the same marks as the map: an
// inference or a possible flag (a fired pattern, in the risk red) is a faded
// dot with a dashed ring, where a confirmed risk hit is solid; a gambling
// platform's wallet is a dot with a dashed halo. The hop map draws these in styles.css, the bubble graph on
// its canvas with FADED and DASH.

export const FADED = 0.45
export const DASH = [2, 1.5]
export const FADED_ROLES = new Set(['inferred', 'flagged'])

export default function RoleSwatch({ role, color }) {
  const faded = FADED_ROLES.has(role)
  return (
    <svg className={`key-swatch role-${role}`} width="14" height="14" viewBox="-7 -7 14 14" aria-hidden="true">
      {role === 'gambling' && <circle className="halo" r="6" fill="none" stroke={color} strokeDasharray={DASH.join(' ')} />}
      <circle
        className="dot" r={faded ? 3.5 : 4} fill={color} fillOpacity={faded ? FADED : undefined}
        stroke={faded ? color : undefined} strokeDasharray={faded ? DASH.join(' ') : undefined}
      />
    </svg>
  )
}
