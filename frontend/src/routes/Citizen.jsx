import Mark from '../components/Mark'
import ThemeToggle from '../components/ThemeToggle'

// The citizen's side of the demo. Citizens get a site of their own, built
// apart from this console; this page only says so. The demo banner
// (App.jsx) is the way back out.
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
          <h1>The citizen site is still being built.</h1>
          <p>Scam victims get a site of their own, separate from this console, to learn what to do and to prepare a complaint. It is not linked from here yet.</p>
        </div>
      </main>
    </div>
  )
}
