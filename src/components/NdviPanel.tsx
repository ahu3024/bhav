import { useEffect, useState } from 'react'
import { getNdvi, friendlyError, type NdviSeries } from '../api'
import { stageWord } from '../plain'

const W = 720
const H = 240
const PAD = { top: 16, right: 16, bottom: 26, left: 34 }
const Y_MIN = 0.1
const Y_MAX = 0.75

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function pct(v: number | null): string {
  return v == null ? '—' : `${Math.round(v * 100)}%`
}

/** Greenness change per day is a tiny number; per-week reads better. */
function rate(v: number | null): string {
  if (v == null) return '—'
  const perWeek = v * 7
  const sign = perWeek > 0 ? '+' : perWeek < 0 ? '−' : ''
  return `${sign}${Math.abs(perWeek).toFixed(3)}/wk`
}

export default function NdviPanel() {
  const [data, setData] = useState<NdviSeries | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    let alive = true
    getNdvi(400)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(friendlyError(e)))
    return () => {
      alive = false
    }
  }, [])

  return (
    <section className="section ndvi" id="satellite">
      <div className="container inner">
        <div className="ndvi__intro">
          <h2 className="section__title">What the satellite sees</h2>
          <p className="prose">
            A satellite photographs the onion belt around Nashik every few days.
            We turn each picture into one simple thing — how green the fields are
            — and one that matters even more: how much of the crop has already
            dried off and is about to head for the mandi.
          </p>
        </div>

        {err && <p className="bt-msg bt-msg--err">{err}</p>}
        {!data && !err && <p className="bt-msg">Looking at the latest satellite picture…</p>}

        {data && (
          <>
            <NdviChart data={data} />
            <NdviStats data={data} />
          </>
        )}
      </div>
    </section>
  )
}

function NdviStats({ data }: { data: NdviSeries }) {
  const c = data.current
  const stats = [
    { k: 'The crop is', v: stageWord(c.stage), note: 'from the latest picture' },
    { k: 'Fields past ripening', v: pct(c.pct_area_past_maturity), note: 'of the whole belt' },
    // With a stale read the curve is only the last composite held forward, so
    // its slope is zero by construction. Reporting that as "no change" would be
    // a measurement we never made.
    c.stale
      ? { k: 'Greening up or drying', v: '—', note: 'clouds are in the way', warn: true }
      : { k: 'Greening up or drying', v: rate(c.greening_rate_per_day), note: 'change each week' },
    {
      k: 'Since the crop was greenest',
      v: c.days_since_peak == null ? '—' : `${c.days_since_peak} days`,
      note: 'the turning point',
    },
    {
      k: 'Last clear picture',
      v: c.obs_age_days == null ? '—'
        : c.obs_age_days === 0 ? 'today' : `${c.obs_age_days} days ago`,
      note: c.stale ? 'clouds have hidden the fields' : 'a fresh look',
      warn: c.stale,
    },
  ]

  return (
    <div className="ndvi__stats">
      {stats.map((s) => (
        <div className="ndvi__stat" key={s.k}>
          <div className="ndvi__stat-k">{s.k}</div>
          <div className="ndvi__stat-v">{s.v}</div>
          <div className={`ndvi__stat-note${s.warn ? ' is-warn' : ''}`}>{s.note}</div>
        </div>
      ))}
    </div>
  )
}

function NdviChart({ data }: { data: NdviSeries }) {
  const days = data.daily.filter((d) => d.smooth != null)
  if (days.length < 2) return null

  const t0 = new Date(days[0].date).getTime()
  const t1 = new Date(days[days.length - 1].date).getTime()
  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom

  const x = (iso: string) =>
    PAD.left + ((new Date(iso).getTime() - t0) / (t1 - t0 || 1)) * plotW
  const y = (v: number) =>
    PAD.top + (1 - (v - Y_MIN) / (Y_MAX - Y_MIN)) * plotH

  const line = days
    .map((d, i) => `${i ? 'L' : 'M'}${x(d.date).toFixed(1)} ${y(d.smooth!).toFixed(1)}`)
    .join(' ')
  const area =
    `${line} L${x(days[days.length - 1].date).toFixed(1)} ${(PAD.top + plotH).toFixed(1)}` +
    ` L${x(days[0].date).toFixed(1)} ${(PAD.top + plotH).toFixed(1)} Z`

  const yThreshold = y(data.maturity_threshold)

  // Month boundaries inside the window, for the x axis.
  const ticks: { at: number; label: string }[] = []
  const cursor = new Date(days[0].date)
  cursor.setDate(1)
  cursor.setMonth(cursor.getMonth() + 1)
  while (cursor.getTime() <= t1) {
    const iso = cursor.toISOString().slice(0, 10)
    ticks.push({
      at: x(iso),
      label: cursor.getMonth() === 0
        ? `${MONTHS[0]} ${String(cursor.getFullYear()).slice(2)}`
        : MONTHS[cursor.getMonth()],
    })
    cursor.setMonth(cursor.getMonth() + 2)
  }

  // Stretches where the last clear pass is old — the monsoon blind spots. Drawn
  // explicitly so the chart never implies we saw something we didn't.
  const blind: { from: number; to: number }[] = []
  let runStart: string | null = null
  for (const d of days) {
    const staleNow = (d.obs_age_days ?? 0) > 21
    if (staleNow && runStart == null) runStart = d.date
    if (!staleNow && runStart != null) {
      blind.push({ from: x(runStart), to: x(d.date) })
      runStart = null
    }
  }
  if (runStart != null) blind.push({ from: x(runStart), to: x(days[days.length - 1].date) })

  return (
    <figure className="ndvi__figure">
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label="How green the Nashik onion fields have been over the last year">
        {/* below the maturity line = crop has dried down */}
        <rect x={PAD.left} y={yThreshold} width={plotW}
          height={PAD.top + plotH - yThreshold} className="ndvi-c__mature" />

        {blind.map((b, i) => (
          <rect key={i} x={b.from} y={PAD.top} width={Math.max(b.to - b.from, 1)}
            height={plotH} className="ndvi-c__blind" />
        ))}

        {[0.2, 0.4, 0.6].map((v) => (
          <g key={v}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)}
              className="ndvi-c__grid" />
            <text x={PAD.left - 8} y={y(v) + 3} className="ndvi-c__ylab">
              {v.toFixed(1)}
            </text>
          </g>
        ))}

        <path d={area} className="ndvi-c__area" />
        <path d={line} className="ndvi-c__line" />

        <line x1={PAD.left} x2={W - PAD.right} y1={yThreshold} y2={yThreshold}
          className="ndvi-c__threshold" />
        <text x={W - PAD.right} y={yThreshold - 6} className="ndvi-c__tlab"
          textAnchor="end">
          maturity {data.maturity_threshold}
        </text>

        {/* every dot is a real 10-day composite */}
        {data.composites.map((c) =>
          c.ndvi == null ? null : (
            <circle key={c.date} cx={x(c.date)} cy={y(c.ndvi)} r={2.6}
              className="ndvi-c__obs" />
          ),
        )}

        {ticks.map((t) => (
          <text key={t.label + t.at} x={t.at} y={H - 8} className="ndvi-c__xlab"
            textAnchor="middle">
            {t.label}
          </text>
        ))}
      </svg>

      <figcaption className="ndvi__legend">
        <span className="ndvi__key ndvi__key--line">How green the fields are</span>
        <span className="ndvi__key ndvi__key--obs">
          An actual satellite picture
        </span>
        <span className="ndvi__key ndvi__key--mature">Crop past ripening</span>
        <span className="ndvi__key ndvi__key--blind">Cloudy — no clear view</span>
      </figcaption>
    </figure>
  )
}
