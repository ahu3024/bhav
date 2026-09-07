import { useEffect, useState } from 'react'
import { signal } from '../data'
import { getAlertToday, sourceOf, formatDate, displayConfidence, type Alert } from '../api'

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
const SAMPLE: Face = { ...signal, confLabel: 'P(UP)' }

const CACHE_KEY = 'bhav:alert:v1'

function readCache(): Alert | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    return raw ? (JSON.parse(raw) as Alert) : null
  } catch {
    return null
  }
}

function toFace(a: Alert): Face {
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
    confidence: displayConfidence(a),
    confLabel: a.calibrated_confidence != null ? 'CALIBRATED' : 'RAW',
    foot: a.reason,
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
            <b>{face.confidence}% confidence</b>
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
  // Seed the live face from cache synchronously — if we've fetched before, the
  // back face is already populated and nothing flickers on refresh.
  const [live, setLive] = useState<Alert | null>(() => readCache())
  const [flipped, setFlipped] = useState(false)

  useEffect(() => {
    let alive = true
    getAlertToday()
      .then((a) => {
        if (!alive) return
        setLive(a)
        try {
          localStorage.setItem(CACHE_KEY, JSON.stringify(a))
        } catch {
          /* private mode — fine, we just re-fetch next load */
        }
      })
      .catch(() => {
        /* backend down — keep cached (or the placeholder) */
      })
    return () => {
      alive = false
    }
  }, [])

  const backFace: Face = live
    ? toFace(live)
    : {
        ref: 'BHAV / LIVE',
        date: '—',
        market: 'NASHIK · ONION',
        action: '—',
        price: '—',
        factors: [{ text: 'Live signal unavailable — start the API', src: ':8000' }],
        confidence: 0,
        confLabel: 'P(UP)',
        foot: 'uvicorn bhav.api:app --reload',
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
          <span className="signal-flip__hint">hover to see the live signal →</span>
        </div>
        <div className="signal-flip__face signal-flip__face--back">
          <CardFace face={backFace} tag="live" />
          <span className="signal-flip__hint">← the sample above is illustrative</span>
        </div>
      </div>
    </div>
  )
}
