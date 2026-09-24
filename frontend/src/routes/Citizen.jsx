import { useNavigate } from 'react-router-dom'
import Mark from '../components/Mark'
import ThemeToggle from '../components/ThemeToggle'
import { signOut } from '../session'

// The citizen's side of Exchequer. Deliberately empty: it is to be built
// during the 24-hour in-person hackathon; only the way back out exists.
export default function Citizen() {
  const navigate = useNavigate()
  return (
    <div className="citizen">
      <header className="citizen-top">
        <span className="brand"><Mark size={20} /><span>Exchequer</span></span>
        <span className="citizen-actions">
          <ThemeToggle />
          <button className="quiet" onClick={() => { signOut(); navigate('/signin/citizen') }}>Sign out</button>
        </span>
      </header>
      <main className="citizen-body">
        <div className="citizen-empty">
          <span className="micro">Citizen portal</span>
          <h1>This page is still to be built.</h1>
          <p>It will be built from the ground up during the 24‑hour in‑person hackathon.</p>
        </div>
      </main>
    </div>
  )
}
