import { useState } from 'react'
import { signal } from '../data'
import { useSnapshot, sourceOf, formatDate, displayConfidence, type Alert } from '../api'
import { sentence } from '../plain'

type Face = {
  ref: string
  date: string
  market: string
  action: string
  price: string
  factors: { text: string; src: string }[]
  confidence: number
  /** Small label beside the confidence bar — what that number actually is. */
  confLabel: string
  foot: string
}

// Front face — the illustrative sample from data.ts. Static, no network, so it
// paints instantly on every refresh with zero buffer.
const SAMPLE: Face = { ...signal, confLabel: 'of similar past weeks' }

function toFace(a: Alert): Face {
  const impact = Math.round(a.expected_impact_per_quintal)
  return {
    ref: 'TODAY',
    date: formatDate(a.date),
    market: `${a.district.toUpperCase()} · ONION`,
    action: a.label.toUpperCase(),
    price: `${impact >= 0 ? '+' : '−'}₹${Math.abs(impact)} / quintal`,
    factors: a.score.factors.slice(0, 3).map((f) => ({
      text: f.phrase,
      src: sourceOf(f.feature),
    })),
    confidence: displayConfidence(a),
    confLabel: 'of similar past weeks',
    foot: `Today’s real call. ${sentence(a.reason)}`,
  }
}

function CardFace({ face, tag }: { face: Face; tag: string }) {
  return (
    <article className="signal-card" aria-label={`Bhav signal (${tag})`}>
      <div className="sc__row sc__head">
        <span className="sc__meta">{face.ref}</span>
        <span className="sc__meta">{face.date}</span>
      </div>

      <div className="sc__title">{face.market}</div>
      <div className="sc__hr" />

      <div className="sc__row sc__action">
        <span className="sc__action-left">
          <span className="sc__k">Action</span>
          <span className="sc__verdict">{face.action}</span>
        </span>
        <span className="sc__price">{face.price}</span>
      </div>

      <div className="sc__factors">
        {face.factors.map((f) => (
          <div className="sc__factor" key={f.text}>
            <span>{f.text}</span>
            <span>{f.src}</span>
          </div>
        ))}

        <div className="sc__conf">
          <div className="sc__conf-row">
            <b>{face.confidence}% went this way</b>
            <span>{face.confLabel}</span>
          </div>
          <div className="sc__bar">
            <i style={{ width: `${face.confidence}%` }} />
          </div>
        </div>
      </div>

      <span className="sc__foot">{face.foot}</span>
    </article>
  )
}

export default function SignalCard() {
  // The shared snapshot hands back the stored answer on the first render, so
  // the back face is already populated and nothing flickers on refresh. A
  // backend that is down or still waking leaves the last known call on screen
  // rather than blanking it.
  const { data: snap } = useSnapshot()
  const live: Alert | null = snap?.alert ?? null
  const [flipped, setFlipped] = useState(false)

  const backFace: Face = live
    ? toFace(live)
    : {
        ref: 'TODAY',
        date: '—',
        market: 'NASHIK · ONION',
        action: '—',
        price: '—',
        factors: [{ text: 'Today’s call is not loading right now', src: 'offline' }],
        confidence: 0,
        confLabel: '',
        foot: 'Check back in a moment',
      }

  return (
    <div
      className={`signal-flip${flipped ? ' is-flipped' : ''}`}
      role="button"
      tabIndex={0}
      aria-label="Signal card — activate to flip between the sample and the live signal"
      onClick={() => setFlipped((v) => !v)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          setFlipped((v) => !v)
        }
      }}
    >
      <div className="signal-flip__inner">
        <div className="signal-flip__face signal-flip__face--front">
          <CardFace face={SAMPLE} tag="sample" />
        </div>
        <div className="signal-flip__face signal-flip__face--back">
          <CardFace face={backFace} tag="live" />
        </div>
      </div>
    </div>
  )
}
