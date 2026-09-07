/**
 * What mattered most in today's call, ranked. Each row names the input, where
 * it came from, and which way it pushed — so the four factor cards above have
 * a summary that can be read in one pass.
 */
import { sentence, SOURCE_LABEL, factorSource } from '../plain'
import type { Alert } from '../api'

export default function DriverList({
  factors,
  limit = 4,
}: {
  factors: Alert['score']['factors']
  limit?: number
}) {
  return (
    <ul className="drivers" data-reveal data-reveal-stagger>
      {factors.slice(0, limit).map((f, i) => {
        const sell = f.direction === 'raises_sell_pressure'
        return (
          <li
            key={f.feature}
            className={`driver driver--${sell ? 'sell' : 'hold'}`}
            style={{ '--i': i } as React.CSSProperties}
          >
            <span className="driver__dot" aria-hidden="true" />
            <span className="driver__text">{sentence(f.phrase)}</span>
            <span className="driver__src">{SOURCE_LABEL[factorSource(f.feature)]}</span>
            <span className="driver__push">
              {sell ? 'points to selling' : 'points to waiting'}
            </span>
          </li>
        )
      })}
    </ul>
  )
}
