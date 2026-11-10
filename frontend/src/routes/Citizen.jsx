import Mark from '../components/Mark'
import ThemeToggle from '../components/ThemeToggle'

// The citizen's side of Exchequer. Deliberately empty for now; the demo
// banner (App.jsx) is the way back out.
export default function Citizen() {
  return (
    <div className="citizen">
      <header className="citizen-top">
        <span className="brand"><Mark size={20} /><span>Exchequer</span></span>
        <span className="citizen-actions">
          <ThemeToggle />
        </span>
      </header>
      <main className="citizen-body">
        <div className="citizen-empty">
          <span className="micro">Citizen portal</span>
          <h1>This page is still to be built.</h1>
          <p>The citizen's side of Exchequer is not open yet. Until it is, the banner above switches back to the investigator view.</p>
        </div>
      </main>
    </div>
  )
}
