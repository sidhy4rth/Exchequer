import { useSyncExternalStore } from 'react'

// The width below which the shell trades its sidebar for a tab bar
// (AppShell.css), and a page may trade a wide table for cards.
export const PHONE = '(max-width: 720px)'

/** Whether the screen matches a media `query`, kept current as it turns or resizes. */
export function useMedia(query) {
  const subscribe = (change) => {
    const list = window.matchMedia?.(query)
    list?.addEventListener('change', change)
    return () => list?.removeEventListener('change', change)
  }
  return useSyncExternalStore(subscribe, () => Boolean(window.matchMedia?.(query).matches))
}

/** Whether the screen is phone-sized. */
export const usePhone = () => useMedia(PHONE)
