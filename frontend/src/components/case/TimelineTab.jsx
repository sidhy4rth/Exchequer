import { timelineStats } from './timelineStats'
import TimelineLanes from './TimelineLanes'
import './Timeline.css'

/** The top of the Timeline tab (pack 2-glass-05): when the money moved, as
 * stat cards worked from the case, then every transfer on a lane chart. */
export default function TimelineTab({ result, unit }) {
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
