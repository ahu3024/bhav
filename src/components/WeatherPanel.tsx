import { useEffect, useState } from 'react'
import { getWeather, friendlyError, type WeatherSeries } from '../api'
import { HARVEST_WINDOW, ROT_RISK } from '../plain'

const W = 720
const H = 220
const PAD = { top: 14, right: 38, bottom: 26, left: 36 }

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Rain is heavily skewed — a few 80 mm days would flatten everything else. */
const RAIN_MAX = 60

export default function WeatherPanel() {
  const [data, setData] = useState<WeatherSeries | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    let alive = true
    getWeather(400)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(friendlyError(e)))
    return () => {
      alive = false
    }
  }, [])

  return (
    <section className="section section--white ndvi weather" id="weather">
      <div className="container inner">
        <div className="ndvi__intro">
          <h2 className="section__title">The weather on your fields</h2>
          <p className="prose">
            Rain and heat decide when the crop can come out of the ground. Damp
            decides whether it will keep once it does — and a farmer who cannot
            store has to sell, whatever the rate. That is how one wet fortnight
            turns into everybody selling at once two weeks later. So we track
            those two questions, not just how many millimetres fell.
          </p>
        </div>

        {err && <p className="bt-msg bt-msg--err">{err}</p>}
        {!data && !err && <p className="bt-msg">Looking up the weather…</p>}

        {data && (
          <>
            <WeatherChart data={data} />
            <WeatherStats data={data} />
            <p className="weather__note">{data.current.note}</p>
          </>
        )}
      </div>
    </section>
  )
}

function WeatherStats({ data }: { data: WeatherSeries }) {
  const c = data.current
  const stats = [
    {
      k: 'Can you lift the crop',
      v: HARVEST_WINDOW[c.harvest_window] ?? c.harvest_window,
      note: 'this fortnight',
      warn: c.harvest_window === 'Poor',
    },
    {
      k: 'Will stored crop keep',
      v: ROT_RISK[c.rot_risk] ?? c.rot_risk,
      note: 'if you hold it back',
      warn: c.rot_risk === 'High',
    },
    {
      k: 'Dry days',
      v: c.dry_days_14 == null ? '—' : `${c.dry_days_14} of ${c.window_days}`,
      note: 'days you could work',
    },
    {
      k: 'Humidity',
      v: c.humidity_mean_14 == null ? '—' : `${Math.round(c.humidity_mean_14)}%`,
      note:
        c.humidity_anom_14 == null
          ? 'over two weeks'
          : `${c.humidity_anom_14 >= 0 ? '+' : '−'}${Math.abs(
              Math.round(c.humidity_anom_14),
            )} against a normal year`,
    },
    {
      k: 'Very hot days',
      v: c.heat_days_14 == null ? '—' : `${c.heat_days_14}`,
      note: 'hotter than 35°C',
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

function WeatherChart({ data }: { data: WeatherSeries }) {
  const days = data.daily
  if (days.length < 2) return null

  const t0 = new Date(days[0].date).getTime()
  const t1 = new Date(days[days.length - 1].date).getTime()
  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const base = PAD.top + plotH

  const x = (iso: string) =>
    PAD.left + ((new Date(iso).getTime() - t0) / (t1 - t0 || 1)) * plotW
  const barW = Math.max(plotW / days.length, 1)

  // Humidity rides on its own 0–100 scale against the right-hand axis.
  const yHum = (v: number) => PAD.top + (1 - v / 100) * plotH
  const humLine = days
    .filter((d) => d.humidity != null)
    .map((d, i) => `${i ? 'L' : 'M'}${x(d.date).toFixed(1)} ${yHum(d.humidity!).toFixed(1)}`)
    .join(' ')

  // Stretches where the crop cannot be lifted — the mechanism, drawn.
  const poor: { from: number; to: number }[] = []
  let run: string | null = null
  for (const d of days) {
    const bad = (d.harvest_score ?? 1) < 0.33
    if (bad && run == null) run = d.date
    if (!bad && run != null) {
      poor.push({ from: x(run), to: x(d.date) })
      run = null
    }
  }
  if (run != null) poor.push({ from: x(run), to: x(days[days.length - 1].date) })

  const ticks: { at: number; label: string }[] = []
  const cursor = new Date(days[0].date)
  cursor.setDate(1)
  cursor.setMonth(cursor.getMonth() + 1)
  while (cursor.getTime() <= t1) {
    ticks.push({
      at: x(cursor.toISOString().slice(0, 10)),
      label: MONTHS[cursor.getMonth()],
    })
    cursor.setMonth(cursor.getMonth() + 2)
  }

  return (
    <figure className="ndvi__figure">
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label="Daily rainfall and humidity for the Nashik onion belt over the last year">
        {poor.map((p, i) => (
          <rect key={i} x={p.from} y={PAD.top} width={Math.max(p.to - p.from, 1)}
            height={plotH} className="wx-c__poor" />
        ))}

        {[25, 50, 75].map((v) => (
          <line key={v} x1={PAD.left} x2={W - PAD.right}
            y1={yHum(v)} y2={yHum(v)} className="ndvi-c__grid" />
        ))}

        {days.map((d) =>
          !d.rain_mm ? null : (
            <rect
              key={d.date}
              x={x(d.date) - barW / 2}
              y={base - Math.min(d.rain_mm / RAIN_MAX, 1) * plotH}
              width={barW}
              height={Math.min(d.rain_mm / RAIN_MAX, 1) * plotH}
              className="wx-c__rain"
            />
          ),
        )}

        <path d={humLine} className="wx-c__hum" />

        <text x={PAD.left - 8} y={base + 3} className="ndvi-c__ylab">0</text>
        <text x={PAD.left - 8} y={PAD.top + 8} className="ndvi-c__ylab">
          {RAIN_MAX}
        </text>
        <text x={W - PAD.right + 8} y={PAD.top + 8} className="wx-c__rlab">100%</text>
        <text x={W - PAD.right + 8} y={base + 3} className="wx-c__rlab">0%</text>

        {ticks.map((t) => (
          <text key={t.label + t.at} x={t.at} y={H - 8} className="ndvi-c__xlab"
            textAnchor="middle">
            {t.label}
          </text>
        ))}
      </svg>

      <figcaption className="ndvi__legend">
        <span className="ndvi__key ndvi__key--rain">Daily rainfall (mm)</span>
        <span className="ndvi__key ndvi__key--hum">Humidity (%)</span>
        <span className="ndvi__key ndvi__key--poor">Harvest stalled</span>
      </figcaption>
    </figure>
  )
}
