import { useCallback } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'

// A case's view lives in its URL (?tab=), so a link or a reload opens the
// view it names. Flow is the default and has no ?tab= of its own.
export const CASE_TABS = [
  { key: 'flow', label: 'Flow' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'entities', label: 'Entities' },
  { key: 'evidence', label: 'Evidence' },
  { key: 'letters', label: 'Letters' },
]
const KEYS = new Set(CASE_TABS.map((t) => t.key))

/** The view ?tab= names; Flow when it names none, or one that is not a view. */
export function tabOf(params) {
  const tab = params.get('tab')
  return KEYS.has(tab) ? tab : 'flow'
}

// What a view is asked to offer first (the Flow tab's cards): a letter, a
// wallet to watch. Kept until the next choice of view.
const ASKS = ['letter', 'watch']

/** [tab, setTab]. Choosing a view replaces the history entry rather than
 * adding one, and keeps the rest of the query (chain, depth, pay) and the
 * navigation state: a trace's result and "started here" ride in it.
 * setTab(tab, { letter, watch }) also names what the view should offer. */
export function useCaseTab() {
  const [params, setParams] = useSearchParams()
  const { state } = useLocation()
  const setTab = useCallback((tab, asks = {}) => setParams((prev) => {
    const next = new URLSearchParams(prev)
    if (tab === 'flow') next.delete('tab')
    else next.set('tab', tab)
    for (const key of ASKS) {
      if (asks[key]) next.set(key, asks[key])
      else next.delete(key)
    }
    return next
  }, { replace: true, state }), [setParams, state])
  return [tabOf(params), setTab]
}
