import { useEffect, useState } from 'react'
import {
  getBacktest,
  getNdviAsOf,
  getWeatherAsOf,
  friendlyError,
  formatDate,
  type Backtest,
  type NdviRead,
  type WeatherRead,
} from '../api'

const COLOR_WORD: Record<string, string> = {
  RED: 'Sell now',
  AMBER: 'Caution',
  GREEN: 'Wait',
}

// Agmarknet history starts 2016-01; the seasonal features need ~a year of
// warm-up, and the label needs 10 days of future prices at the other end.
const MIN_DATE = '2017-03-01'
const MAX_DATE = new Date(Date.now() - 14 * 864e5).toISOString().slice(0, 10)

// Real events from the Agmarknet series, not illustrative dates.
const PRESETS = [
  { date: '2019-12-03', label: 'Dec 2019', note: 'record ₹8,864, then −50%' },
  { date: '2021-03-02', label: 'Mar 2021', note: 'rabi glut' },
  { date: '2024-12-10', label: 'Dec 2024', note: 'post-peak slide' },
]
const DEFAULT_DATE = PRESETS[0].date

function rupee(n: number): string {
  const s = Math.round(Math.abs(n)).toLocaleString('en-IN')
  return `${n < 0 ? '−' : ''}₹${s}`
}

export default function BacktestPage() {
  const [date, setDate] = useState(DEFAULT_DATE)
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [res, setRes] = useState<Backtest | null>(null)
  const [ndvi, setNdvi] = useState<NdviRead | null>(null)
  const [wx, setWx] = useState<WeatherRead | null>(null)
  const [err, setErr] = useState('')

  async function run(d: string = date) {
    setState('loading')
    setErr('')
    setNdvi(null)
    setWx(null)
    try {
      const [bt, sat, weather] = await Promise.all([
        getBacktest(d),
        // Satellite and weather are context, not the verdict — never fail the
        // run just because one of them is missing for that date.
        getNdviAsOf(d).catch(() => null),
        getWeatherAsOf(d).catch(() => null),
      ])
      setRes(bt)
      setNdvi(sat)
      setWx(weather)
      setState('idle')
    } catch (e) {
      setErr(friendlyError(e))
      setState('error')
    }
  }

  // Run the default date once so the page never opens empty.
  useEffect(() => {
    void run(DEFAULT_DATE)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const a = res?.alert
  const r = res?.realized
  const o = res?.outcome

  return (
    <main>
      <section className="section page-head">
        <div className="container inner">
          <p className="eyebrow">— Time travel —</p>
          <h1 className="page-title">
            Pick any past date. See what Bhav would have said — and what the
            market actually did.
          </h1>
          <p className="prose">
            The same scoring code as the live signal, rewound. Every feature is
            point-in-time: nothing in this result knows anything that hadn't
            happened yet on the date you choose. No cherry-picked wins — the
            outcome is the real price move over the next 10 days, priced in
            ₹/quintal against the habit the alert argues against.
          </p>
        </div>
      </section>

      <section className="section section--white">
        <div className="container inner">
          <div className="bt-panel bt-panel--page">
            <div className="bt-form">
              <label htmlFor="bt-date">Backtest date</label>
              <input
                id="bt-date"
                type="date"
                value={date}
                min={MIN_DATE}
                max={MAX_DATE}
                onChange={(e) => setDate(e.target.value)}
              />
              <button
                className="bt-run"
                onClick={() => run()}
                disabled={state === 'loading'}
              >
                {state === 'loading' ? 'Running…' : 'Run backtest'}
              </button>
            </div>

            <div className="bt-presets">
              {PRESETS.map((p) => (
                <button
                  key={p.date}
                  className="bt-link"
                  onClick={() => {
                    setDate(p.date)
                    void run(p.date)
                  }}
                >
                  {p.label} <span className="bt-preset-note">{p.note}</span>
                </button>
              ))}
            </div>

            {state === 'error' && <p className="bt-msg bt-msg--err">{err}</p>}

            {a && r && o && state !== 'error' && (
              <div className="bt-result">
                <div className="bt-head">
                  <span className={`bt-chip bt-chip--${a.color.toLowerCase()}`}>
                    {COLOR_WORD[a.color]}
                  </span>
                  <span className="bt-asof">signal as of {formatDate(a.date)}</span>
                </div>

                <p className="bt-reason">{a.reason}</p>

                <div className="bt-cols">
                <div className="fingerprint__rows">
                  <div className="fp-row">
                    <dt>Price that day</dt>
                    <dd className="mono">{rupee(r.price_now)}/qtl</dd>
                  </div>
                  <div className="fp-row">
                    <dt>Low over next {r.horizon_days} days</dt>
                    <dd className="mono">
                      {r.price_min != null ? `${rupee(r.price_min)}/qtl` : '—'}
                    </dd>
                  </div>
                  <div className="fp-row">
                    <dt>Actual move</dt>
                    <dd
                      className={
                        r.max_drop_pct != null && r.max_drop_pct <= -0.1 ? 'hot' : 'mono'
                      }
                    >
                      {r.max_drop_pct != null
                        ? `${(r.max_drop_pct * 100).toFixed(1)}%`
                        : '—'}
                    </dd>
                  </div>
                  <div className="fp-row">
                    <dt>Followed Bhav — {o.action}</dt>
                    <dd className="mono">
                      {rupee(o.strategy_price_per_quintal)}/qtl
                    </dd>
                  </div>
                  <div className="fp-row">
                    <dt>Instead of — {o.baseline_label}</dt>
                    <dd className="mono">
                      {rupee(o.baseline_price_per_quintal)}/qtl
                    </dd>
                  </div>
                </div>

                  <div className="bt-context">
                    {ndvi && <SatelliteContext read={ndvi} />}
                    {wx && <WeatherContext read={wx} />}
                  </div>
                </div>

                <div className="bt-verdict">
                  <div>
                    <span className="bt-delta">
                      {o.delta_per_quintal >= 0 ? '+' : ''}
                      {rupee(o.delta_per_quintal)}/qtl
                    </span>
                    <span className="bt-delta-pct">
                      {' '}
                      ({(o.delta_pct * 100).toFixed(1)}%)
                    </span>
                  </div>
                  {o.call_was_right != null && (
                    <span className={`bt-badge ${o.call_was_right ? 'hit' : 'miss'}`}>
                      {o.call_was_right ? 'Call held up' : 'Call missed'}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

    </main>
  )
}

/** What Sentinel-2 saw on the backtested date — the crop side of the call. */
function SatelliteContext({ read }: { read: NdviRead }) {
  const rows: [string, string][] = [
    ['Crop stage', read.stage],
    [
      'Belt past maturity',
      read.pct_area_past_maturity == null
        ? '—'
        : `${Math.round(read.pct_area_past_maturity * 100)}%`,
    ],
    [
      'Days since greenness peak',
      read.days_since_peak == null ? '—' : `${read.days_since_peak}`,
    ],
    [
      'Satellite read',
      read.obs_age_days == null
        ? '—'
        : `${read.obs_age_days} day${read.obs_age_days === 1 ? '' : 's'} old${
            read.stale ? ' — stale' : ''
          }`,
    ],
  ]

  return (
    <div className="bt-sat">
      <div className="bt-sat__head">What the satellite saw that day</div>
      <div className="fingerprint__rows">
        {rows.map(([k, v]) => (
          <div className="fp-row" key={k}>
            <dt>{k}</dt>
            <dd className="mono">{v}</dd>
          </div>
        ))}
      </div>
    </div>
  )
}


/** What the weather overlay said that day — the ground side of the call. */
function WeatherContext({ read }: { read: WeatherRead }) {
  const rows: [string, string][] = [
    ['Harvest window', read.harvest_window],
    ['Storage risk', read.rot_risk],
    [
      'Dry days',
      read.dry_days_14 == null ? '—' : `${read.dry_days_14}/${read.window_days}`,
    ],
    [
      'Humidity',
      read.humidity_mean_14 == null ? '—' : `${Math.round(read.humidity_mean_14)}%`,
    ],
  ]

  return (
    <div className="bt-sat">
      <div className="bt-sat__head">What the weather said that day</div>
      <div className="fingerprint__rows">
        {rows.map(([k, v]) => (
          <div className="fp-row" key={k}>
            <dt>{k}</dt>
            <dd className="mono">{v}</dd>
          </div>
        ))}
      </div>
      <p className="bt-sat__note">{read.note}</p>
    </div>
  )
}
