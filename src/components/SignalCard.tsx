import { useEffect, useState } from 'react'
import { signal } from '../data'
import { getAlertToday, sourceOf, formatDate, type Alert } from '../api'

type View = {
  ref: string
  date: string
  market: string
  action: string
  price: string
  factors: { text: string; src: string }[]
  confidence: number
  foot: string
  live: boolean
}

const MOCK: View = { ...signal, live: false }

function toView(a: Alert): View {
  const impact = Math.round(a.expected_impact_per_quintal)
  return {
    ref: `BHAV / ${a.score.model_kind.toUpperCase()} · LIVE`,
    date: formatDate(a.date),
    market: `${a.district.toUpperCase()} · ONION`,
    action: a.label.toUpperCase(),
    price: `${impact >= 0 ? '+' : '−'}₹${Math.abs(impact)} / QTL`,
    factors: a.score.factors.slice(0, 3).map((f) => ({
      text: f.phrase,
      src: sourceOf(f.feature),
    })),
    confidence: a.confidence,
    foot: a.reason,
    live: true,
  }
}

export default function SignalCard() {
  const [view, setView] = useState<View>(MOCK)

  useEffect(() => {
    let alive = true
    getAlertToday()
      .then((a) => alive && setView(toView(a)))
      .catch(() => alive && setView(MOCK)) // backend down -> keep the sample
    return () => {
      alive = false
    }
  }, [])

  return (
    <article className="signal-card" aria-label="Bhav signal">
      <div className="sc__row sc__head">
        <span className="sc__meta">{view.ref}</span>
        <span className="sc__meta">{view.date}</span>
      </div>

      <div className="sc__title">
        {view.market}
        {!view.live && ' · SAMPLE'}
      </div>
      <div className="sc__hr" />

      <div className="sc__row sc__action">
        <span className="sc__action-left">
          <span className="sc__k">Action</span>
          <span className="sc__verdict">{view.action}</span>
        </span>
        <span className="sc__price">{view.price}</span>
      </div>

      <div className="sc__factors">
        {view.factors.map((f) => (
          <div className="sc__factor" key={f.text}>
            <span>{f.text}</span>
            <span>{f.src}</span>
          </div>
        ))}

        <div className="sc__conf">
          <div className="sc__conf-row">
            <b>{view.confidence}% confidence</b>
            <span>P(UP)</span>
          </div>
          <div className="sc__bar">
            <i style={{ width: `${view.confidence}%` }} />
          </div>
        </div>
      </div>

      <span className="sc__foot">{view.foot}</span>
    </article>
  )
}
