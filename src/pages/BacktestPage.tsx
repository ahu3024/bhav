import { useEffect, useState } from 'react'
import { useReveal } from '../useReveal'
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
import {
  VERDICT,
  stageWord,
  HARVEST_WINDOW,
  ROT_RISK,
  rupees,
  perQuintal,
  percent,
  sentence,
} from '../plain'

// Agmarknet history starts 2016-01; the seasonal features need ~a year of
// warm-up, and the label needs 10 days of future prices at the other end.
const MIN_DATE = '2017-03-01'
const MAX_DATE = new Date(Date.now() - 14 * 864e5).toISOString().slice(0, 10)

// The three sharpest 10-day falls in the price series actually loaded, one per
// year. Taken from the data rather than from headlines: quoting a real-world
// record the loaded series does not contain is the fastest way to lose a room.
const PRESETS = [
  { date: '2019-04-17', label: 'April 2019', note: 'the rate fell by a third in ten days' },
  { date: '2021-04-10', label: 'April 2021', note: 'harvest glut, rate down 29%' },
  { date: '2023-04-18', label: 'April 2023', note: 'the same story again, down 27%' },
]
const DEFAULT_DATE = PRESETS[0].date

export default function BacktestPage() {
  const [date, setDate] = useState(DEFAULT_DATE)
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [res, setRes] = useState<Backtest | null>(null)
  const [ndvi, setNdvi] = useState<NdviRead | null>(null)
  const [wx, setWx] = useState<WeatherRead | null>(null)
  const [err, setErr] = useState('')

  // The result is replaced on every run, so re-scan when it changes.
  useReveal([res, ndvi, wx])

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
  const right = o?.call_was_right

  return (
    <main>
      <section className="section page-head">
        <div className="container inner">
          <p className="eyebrow">— Check our record —</p>
          <h1 className="page-title">
            Pick any day from the past. See what we would have told you — and
            what the mandi actually did next.
          </h1>
          <p className="prose">
            This runs the same thing that makes today’s call, but rewound. It
            only ever sees what was known on the day you pick — never what came
            afterwards. The wrong calls show up here too; we don’t hide them.
          </p>
        </div>
      </section>

      <section className="section section--white">
        <div className="container inner">
          <div className="bt-panel bt-panel--page">
            <div className="bt-form">
              <label htmlFor="bt-date">Pick a day</label>
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
                {state === 'loading' ? 'Checking…' : 'Show me'}
              </button>
            </div>

            <div className="bt-presets">
              <span className="bt-presets__k">Or try a week people remember:</span>
              {PRESETS.map((p) => (
                <button
                  key={p.date}
                  className="bt-link"
                  onClick={() => {
                    setDate(p.date)
                    void run(p.date)
                  }}
                >
                  {p.label} <span className="bt-preset-note">— {p.note}</span>
                </button>
              ))}
            </div>

            {state === 'error' && <p className="bt-msg bt-msg--err">{err}</p>}

            {a && r && o && state !== 'error' && (
              <div className="bt-result">
                <div className="bt-head">
                  <span className={`bt-chip bt-chip--${a.color.toLowerCase()}`}>
                    {VERDICT[a.color].word}
                  </span>
                  <span className="bt-asof">
                    is what we would have said on {formatDate(a.date)}
                  </span>
                </div>

                <p className="bt-reason">{sentence(a.reason)}</p>

                {/* the two outcomes, side by side — the heart of the page */}
                <div className="bt-compare" data-reveal data-reveal-stagger>
                  <div className="bt-compare__col bt-compare__col--ours" style={{ '--i': 0 } as React.CSSProperties}>
                    <span className="bt-compare__k">If you had followed us</span>
                    <span className="bt-compare__v">
                      {rupees(o.strategy_price_per_quintal)}
                    </span>
                    <span className="bt-compare__note">
                      per quintal — {o.action}
                    </span>
                  </div>
                  <div
                    className="bt-compare__col"
                    style={{ '--i': 1 } as React.CSSProperties}
                  >
                    <span className="bt-compare__k">If you had not</span>
                    <span className="bt-compare__v">
                      {rupees(o.baseline_price_per_quintal)}
                    </span>
                    <span className="bt-compare__note">
                      per quintal — {o.baseline_label}
                    </span>
                  </div>
                </div>

                <div className="bt-verdict">
                  <div>
                    <span className="bt-delta">
                      {o.delta_per_quintal >= 0 ? '+' : '−'}
                      {rupees(Math.abs(o.delta_per_quintal))}
                    </span>
                    <span className="bt-delta-pct"> per quintal difference</span>
                  </div>
                  {right != null && (
                    <span className={`bt-badge ${right ? 'hit' : 'miss'}`}>
                      {right ? 'We got this one right' : 'We got this one wrong'}
                    </span>
                  )}
                </div>

                <div className="bt-cols" data-reveal>
                  <div className="bt-sat">
                    <div className="bt-sat__head">What the mandi did next</div>
                    <div className="fingerprint__rows">
                      <Row k="Rate that day" v={perQuintal(r.price_now)} />
                      <Row
                        k={`Lowest over the next ${r.horizon_days} days`}
                        v={r.price_min == null ? '—' : perQuintal(r.price_min)}
                      />
                      <Row
                        k="Which was a move of"
                        v={
                          r.max_drop_pct == null
                            ? '—'
                            : `${r.max_drop_pct <= 0 ? 'down' : 'up'} ${percent(Math.abs(r.max_drop_pct), 1)}`
                        }
                        hot={r.max_drop_pct != null && r.max_drop_pct <= -0.1}
                      />
                    </div>
                  </div>

                  <div className="bt-context">
                    {ndvi && <SatelliteContext read={ndvi} />}
                    {wx && <WeatherContext read={wx} />}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>
    </main>
  )
}

function Row({ k, v, hot }: { k: string; v: string; hot?: boolean }) {
  return (
    <div className="fp-row">
      <dt>{k}</dt>
      <dd className={hot ? 'hot' : 'mono'}>{v}</dd>
    </div>
  )
}

/** What the satellite saw that day — the crop side of the call. */
function SatelliteContext({ read }: { read: NdviRead }) {
  return (
    <div className="bt-sat">
      <div className="bt-sat__head">What the crop looked like from space</div>
      <div className="fingerprint__rows">
        <Row k="The crop was" v={stageWord(read.stage)} />
        <Row
          k="Fields past ripening"
          v={percent(read.pct_area_past_maturity)}
        />
        <Row
          k="Satellite picture was"
          v={
            read.obs_age_days == null
              ? '—'
              : `${read.obs_age_days} day${read.obs_age_days === 1 ? '' : 's'} old${
                  read.stale ? ' — clouds had hidden the fields' : ''
                }`
          }
        />
      </div>
    </div>
  )
}

/** What the weather was doing that day — the ground side of the call. */
function WeatherContext({ read }: { read: WeatherRead }) {
  return (
    <div className="bt-sat">
      <div className="bt-sat__head">What the weather was doing</div>
      <div className="fingerprint__rows">
        <Row
          k="Could you lift the crop"
          v={HARVEST_WINDOW[read.harvest_window] ?? read.harvest_window}
        />
        <Row
          k="Would stored crop keep"
          v={ROT_RISK[read.rot_risk] ?? read.rot_risk}
        />
        <Row
          k="Dry days in that fortnight"
          v={read.dry_days_14 == null ? '—' : `${read.dry_days_14} of ${read.window_days}`}
        />
      </div>
      <p className="bt-sat__note">{read.note}</p>
    </div>
  )
}
