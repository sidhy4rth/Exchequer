import { useEffect, useState } from 'react'
import { currentTheme, toggleTheme } from '../theme'

/** Sun / moon switch for the top bar. */
export default function ThemeToggle() {
  const [theme, setTheme] = useState(currentTheme())
  useEffect(() => {
    const onChange = (e) => setTheme(e.detail)
    window.addEventListener('themechange', onChange)
    return () => window.removeEventListener('themechange', onChange)
  }, [])
  const dark = theme === 'dark'
  return (
    <button type="button" className="theme-toggle" onClick={toggleTheme}
      title={dark ? 'Switch to the light case-file skin' : 'Switch to the dark console skin'}
      aria-label="Toggle colour theme">
      {dark ? (
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <circle cx="8" cy="8" r="3" /><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
          <path d="M13.5 10.2A6 6 0 0 1 5.8 2.5a6 6 0 1 0 7.7 7.7z" />
        </svg>
      )}
    </button>
  )
}
