// Two skins over one set of tokens. Dark is the default: a near-black surface
// with serif headings and monospace labels, the look of an operations console
// rather than a printed page. Light is the case-file look, one click away,
// for a bright room or a printout. The choice is per browser and remembered.
//
// GraphView paints on a canvas and cannot read CSS variables per frame, so it
// subscribes to `themechange` and re-reads its palette when the skin flips.

const KEY = 'exchequer-theme'

export function currentTheme() {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = theme
  try { localStorage.setItem(KEY, theme) } catch { /* private mode */ }
  window.dispatchEvent(new CustomEvent('themechange', { detail: theme }))
}

export function initTheme() {
  let saved = null
  try { saved = localStorage.getItem(KEY) } catch { /* private mode */ }
  document.documentElement.dataset.theme = saved === 'light' ? 'light' : 'dark'
}

export function toggleTheme() {
  applyTheme(currentTheme() === 'dark' ? 'light' : 'dark')
}

/** Read one CSS token as the browser resolved it for the current skin. */
export function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}
