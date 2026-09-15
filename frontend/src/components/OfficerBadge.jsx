import { useAuth } from '../auth'

/** Who is signed in, and the way out. Renders nothing on an ungated instance. */
export default function OfficerBadge() {
  const { required, officer, signOut } = useAuth()
  if (!required || !officer) return null
  return (
    <span className="officer">
      <span className="who" title={[officer.officer_id && `ID ${officer.officer_id}`, officer.unit].filter(Boolean).join(' · ')}>
        {officer.name}
      </span>
      <button type="button" className="quiet" onClick={signOut}>Sign out</button>
    </span>
  )
}
