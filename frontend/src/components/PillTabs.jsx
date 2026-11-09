import { useId, useRef, useState } from 'react'

const STEP = { ArrowRight: 1, ArrowLeft: -1 }

/** Pill tabs for any page: a named tablist, one panel per tab. The arrow
 * keys move between tabs and choose as they go (Home and End jump to the
 * ends); only the chosen tab takes Tab focus, so Tab goes on to its panel.
 * Every panel stays mounted and is hidden when not chosen. Pass `value` and
 * `onChange` for the page to hold the choice, or neither for the tabs to. */
export default function PillTabs({ label, tabs, value, onChange }) {
  const base = useId()
  const [own, setOwn] = useState(tabs[0]?.key)
  const current = value ?? own
  const refs = useRef({})
  const id = (part, key) => `${base}-${part}-${key}`

  function choose(key) {
    if (value === undefined) setOwn(key)
    onChange?.(key)
  }

  function onKeyDown(event) {
    const at = tabs.findIndex((t) => t.key === current)
    const to = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : STEP[event.key] === undefined ? null : at + STEP[event.key]
    if (to === null) return
    event.preventDefault()
    const next = tabs[(to + tabs.length) % tabs.length]
    choose(next.key)
    refs.current[next.key]?.focus()
  }

  return (
    <div className="pill-tabs">
      <div role="tablist" aria-label={label} className="pill-tablist" onKeyDown={onKeyDown}>
        {tabs.map((t) => (
          <button key={t.key} ref={(el) => { refs.current[t.key] = el }} type="button" role="tab" id={id('tab', t.key)}
            aria-controls={id('panel', t.key)} aria-selected={t.key === current} tabIndex={t.key === current ? 0 : -1}
            onClick={() => choose(t.key)}>
            {t.icon}{t.label}
          </button>
        ))}
      </div>
      {tabs.map((t) => (
        <div key={t.key} role="tabpanel" id={id('panel', t.key)} aria-labelledby={id('tab', t.key)} hidden={t.key !== current} tabIndex={0}>
          {t.content}
        </div>
      ))}
    </div>
  )
}
