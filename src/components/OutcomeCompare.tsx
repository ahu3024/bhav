/**
 * The point of the backtest page: what following the call was worth against
 * what ignoring it was worth, and the gap between them. The two figures and
 * the gap are one panel rather than three stacked blocks — the comparison only
 * means anything read together.
 */
import { useCountUp } from '../useReveal'
import { rupees } from '../plain'

export default function OutcomeCompare({
  ours,
  oursNote,
  theirs,
  theirsNote,
  delta,
  right,
}: {
  ours: number
  oursNote: string
  theirs: number
  theirsNote: string
  delta: number
  right: boolean | null | undefined
}) {
  const a = useCountUp(Math.round(ours))
  const b = useCountUp(Math.round(theirs))
  const gap = useCountUp(Math.round(Math.abs(delta)))

  return (
    <div className="outcome" data-reveal>
      <div className="outcome__pair">
        <div className="outcome__col outcome__col--ours">
          <span className="outcome__k">If you had followed us</span>
          <span className="outcome__v">{rupees(a)}</span>
          <span className="outcome__note">per quintal — {oursNote}</span>
        </div>

        <div className="outcome__gap" aria-hidden="true">
          <span className="outcome__vs">vs</span>
        </div>

        <div className="outcome__col">
          <span className="outcome__k">If you had not</span>
          <span className="outcome__v">{rupees(b)}</span>
          <span className="outcome__note">per quintal — {theirsNote}</span>
        </div>
      </div>

      <div className="outcome__foot">
        <p className="outcome__delta">
          <span className={`outcome__delta-v ${delta >= 0 ? 'is-up' : 'is-down'}`}>
            {delta >= 0 ? '+' : '−'}
            {rupees(gap)}
          </span>
          <span className="outcome__delta-k"> a quintal between the two</span>
        </p>
        {right != null && (
          <span className={`verdict-badge ${right ? 'is-hit' : 'is-miss'}`}>
            <i aria-hidden="true" />
            {right ? 'We got this one right' : 'We got this one wrong'}
          </span>
        )}
      </div>
    </div>
  )
}
