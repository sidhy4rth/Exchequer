import { memo } from 'react'
import { timelineStats } from './timelineStats'
import TimelineLanes from './TimelineLanes'
import './Timeline.css'

/** The top of the Timeline tab (pack 2-glass-05): when the money moved, as
 * stat cards worked from the case, then every transfer on a lane chart. */
function TimelineTab({ result, unit }) {
  const cards = timelineStats(result)
  return <>
    {cards.length > 0 && (
      <ul className="tl-stats" aria-label="When the money moved">
        {cards.map((c) => (
          <li key={c.key} className={`tl-stat ${c.tone}`}><strong>{c.value}</strong><span>{c.caption}</span></li>
        ))}
      </ul>
    )}
    <TimelineLanes result={result} unit={unit} />
  </>
}

// Skips a render while the case is the same: the page re-renders as rows
// reveal, and a dense case's lanes take tens of ms to draw.
export default memo(TimelineTab)
