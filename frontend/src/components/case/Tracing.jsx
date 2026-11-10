import { useRef } from 'react'

// What a live trace shows while it runs: four steps, each mapped to the
// stages the backend reports as it works (app/jobs.py "starting",
// graph_builder.py "walking", pipeline.py "screening", "attributing",
// "following_swap"), the time so far, a bar that only moves forward, and Stop.

const STEP_OF = { starting: 0, walking: 1, screening: 2, attributing: 3, following_swap: 3, saving: 3, done: 4 }

/** jobs.py merges each report into the last, so the walk that follows a swap
 * reports walking, screening and attributing again with follow_asset still
 * set: that is all the last step. Done ticks every step. */
const stepOf = (p) => (p?.follow_asset && p.stage !== 'done' ? 3 : STEP_OF[p?.stage] ?? 0)

const STAGE_TEXT = {
  starting: 'Starting',
  screening: 'Walk finished · screening against sanctions, mixer and freeze lists',
  attributing: 'Matching exchanges and inferring deposit addresses',
  following_swap: 'Following the funds after a swap',
  saving: 'Saving the case',
}

/** One line on what the background trace is doing right now. */
function describeProgress(p) {
  if (p.stage === 'walking') {
    const hop = `Hop ${p.hop}${p.max_depth ? ` of ${p.max_depth}` : ''}`
    const read = p.level_size > 1 ? ` · ${p.level_read ?? 0} of ${p.level_size} addresses read` : ''
    const seen = p.addresses ? ` · ${p.addresses} address${p.addresses === 1 ? '' : 'es'} so far` : ''
    return (p.follow_asset ? `In ${p.follow_asset} after the swap · ` : '') + hop + read + seen
  }
  if (p.stage === 'following_swap') return `${STAGE_TEXT.following_swap}${p.follow_asset ? ` into ${p.follow_asset}` : ''}`
  return STAGE_TEXT[p.stage] ?? ''
}

/** How far through the four steps, 0 to 100: a step is a quarter, and the
 * walk moves through its quarter hop by hop, address by address. */
function percent(p, step) {
  let within = 0
  if (p?.stage === 'walking' && p.max_depth) {
    const level = p.level_size > 0 ? Math.min(1, (p.level_read ?? 0) / p.level_size) : 0
    within = Math.min(1, ((p.hop ?? 1) - 1 + level) / p.max_depth)
  }
  return Math.round((100 * (step + within)) / 4)
}

const mmss = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
function clock(seconds) {
  const tenths = Math.floor(seconds * 10)
  return `${Math.floor(tenths / 600)}:${((tenths % 600) / 10).toFixed(1).padStart(4, '0')}`
}

export default function Tracing({ address, chain, asset, reverse, payments, progress, elapsed, budget, canStop, stopping, onStop }) {
  // The furthest the screen has gone: a failed job, or a stage no step
  // names, holds it there. A new trace starts from no progress at all.
  const furthest = useRef([0, 0])
  if (!progress) furthest.current = [0, 0]
  const step = Math.max(furthest.current[0], stepOf(progress))
  const pct = Math.max(furthest.current[1], percent(progress, step))
  furthest.current = [step, pct]
  const steps = [
    payments ? ['Find the payment', "the victim's payment, read from the chain"] : ['Start from the address', 'its own history, read from the chain'],
    ['Follow it hop by hop', reverse ? 'incoming transfers, walked backwards' : 'money that left after it arrived'],
    ['Screen every wallet', 'exchanges, sanctions, mixers, freezes'],
    ['Show where it is now', 'the exchange it reached, and how much'],
  ]
  return (
    <section className="tracing" aria-labelledby="tracing-title">
      <div className="tracing-head">
        <div>
          <p className="mono">{address} · {chain} {asset}</p>
          <h1 id="tracing-title">Following the money</h1>
        </div>
        {canStop && <button type="button" className="tracing-stop" disabled={stopping} onClick={onStop}>{stopping ? 'Stopping…' : 'Stop this trace'}</button>}
      </div>
      <div className="tracing-card">
        <ol className="tracing-steps" aria-label="Steps">
          {steps.map(([label, sub], i) => {
            const state = i < step ? 'done' : i === step ? 'now' : 'next'
            return (
              <li key={label} className={`tracing-step ${state}`} aria-current={state === 'now' ? 'step' : undefined}>
                <span className="tracing-mark" aria-hidden="true">
                  {state === 'done' && <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2.5 6.2l2.4 2.4 4.6-4.8" /></svg>}
                </span>
                <span className="visually-hidden">{state === 'done' ? 'Done: ' : state === 'now' ? 'Now: ' : 'Next: '}</span>
                <span className="tracing-label">{label}</span>
                <small>{sub}</small>
              </li>
            )
          })}
        </ol>
        {progress && <p className="progress-line" aria-live="polite">{describeProgress(progress)}</p>}
        <div className="tracing-bar" role="progressbar" aria-label="Trace progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
          <span style={{ width: `${pct}%` }} />
        </div>
        <p className="tracing-foot">
          <span>{budget ? <>stops expanding at {mmss(budget)}{elapsed > budget ? ' — finishing what it has' : ''}</> : 'One request per address, about two a second on a free key. Instant when the addresses have been seen before.'}</span>
          <span className="mono">{clock(elapsed)}</span>
        </p>
      </div>
    </section>
  )
}
