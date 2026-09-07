import { useEffect, useState } from 'react'
import { useReveal, useCountUp } from '../useReveal'
import {
  getAlertToday,
  getNdvi,
  getWeather,
  friendlyError,
  formatDate,
  type Alert,
  type NdviSeries,
  type WeatherSeries,
} from '../api'
import {
  VERDICT,
  stageWord,
  HARVEST_WINDOW,
  ROT_RISK,
  rupees,
  perQuintal,
  percent,
  worthLine,
  confidenceLine,
  factorSource,
  SOURCE_LABEL,
  sentence,
} from '../plain'

export default function TodayPage() {
  const [alert, setAlert] = useState<Alert | null>(null)
  const [ndvi, setNdvi] = useState<NdviSeries | null>(null)
  const [wx, setWx] = useState<WeatherSeries | null>(null)
  const [err, setErr] = useState('')

  // Re-scan once the data lands, since most of the page does not exist until then.
  useReveal([alert, ndvi, wx])

  // Hooks run unconditionally on every render — including the loading and
  // error ones, before `alert` exists — so the animated figures are computed
  // here, fed 0 until there is a real number, rather than after the early
  // returns below. The count then plays out the moment the real value lands.
  const worth = alert ? worthLine(alert) : null
  const confidence = alert ? alert.calibrated_confidence ?? alert.confidence : 0
  const animatedWorth = useCountUp(worth?.value ?? 0)
  const animatedConfidence = useCountUp(confidence)

  useEffect(() => {
    let alive = true
    getAlertToday()
      .then(async (a) => {
        if (!alive) return
        setAlert(a)
        // Context, never the verdict — a missing panel must not blank the page.
        const [sat, weather] = await Promise.all([
          getNdvi(120).catch(() => null),
          getWeather(120).catch(() => null),
        ])
        if (!alive) return
        setNdvi(sat)
        setWx(weather)
      })
      .catch((e) => alive && setErr(friendlyError(e)))
    return () => {
      alive = false
    }
  }, [])

  if (err) {
    return (
      <main>
        <section className="section page-head">
          <div className="container inner">
            <h1 className="page-title">Today’s call</h1>
            <p className="bt-msg bt-msg--err">{err}</p>
          </div>
        </section>
      </main>
    )
  }

  if (!alert || !worth) {
    return (
      <main>
        <section className="section page-head">
          <div className="container inner">
            <h1 className="page-title">Today’s call</h1>
            <p className="prose">Reading the latest satellite, weather and mandi data…</p>
          </div>
        </section>
      </main>
    )
  }

  const v = VERDICT[alert.color]
  const sat = ndvi?.current
  const weather = wx?.current
  const waiting = alert.color === 'GREEN'

  return (
    <main className="today">
      {/* ---- the answer, before anything else ---- */}
      <section
        className={`today__verdict today__verdict--${alert.color.toLowerCase()}${waiting ? ' today__verdict--waiting' : ''}`}
      >
        <div className="container today__grid">
          <div className="today__main">
            <p className="today__where">Onion · Nashik · {formatDate(alert.date)}</p>
            <h1 className="today__word">{v.word}</h1>
            <p className="today__line">{v.line}</p>

            <div className="today__money">
              <span className="today__amount">
                {worth.prefix}
                {rupees(animatedWorth)}
                {worth.suffix}
              </span>
              <span className="today__caption">{worth.caption}</span>
            </div>

            {/* "Wait" is an ongoing state, not a one-off verdict — say so, so the
                banner reads as a thing still in motion rather than a dead end. */}
            {waiting && (
              <p className="today__watch">
                <span className="today__watch-dot" aria-hidden="true" />
                Still watching, every day — your weekly WhatsApp alert will say
                the moment this changes
              </p>
            )}
          </div>

          {/* the numbers a farmer checks second — kept out of the headline but
              on the same screen, so the banner is not half empty */}
          <aside className="glance">
            <div className="glance__row">
              <span className="glance__k">Best days to sell</span>
              <span className="glance__v">
                {formatDate(alert.window_start)} — {formatDate(alert.window_end)}
              </span>
            </div>
            <div className="glance__row">
              <span className="glance__k">Rate in the mandi today</span>
              <span className="glance__v">
                {perQuintal(alert.score.price_per_quintal)}
              </span>
            </div>
            <div className="glance__row">
              <span className="glance__k">How often this pattern held</span>
              <span className="glance__v">{animatedConfidence} out of 100 weeks</span>
              <span className="glance__bar" aria-hidden="true">
                <i style={{ width: `${animatedConfidence}%` }} />
              </span>
            </div>
            {sat && (
              <div className="glance__row">
                <span className="glance__k">The crop right now</span>
                <span className="glance__v">{stageWord(sat.stage)}</span>
              </div>
            )}
          </aside>
        </div>
      </section>

      {/* ---- why ---- */}
      <section className="section section--white">
        <div className="container inner">
          <h2 className="section__title">Why we’re saying this</h2>
          <p className="prose">
            Four things go into every call. Here is what each one looked like
            today, and today’s mandi rate is {perQuintal(alert.score.price_per_quintal)}.
          </p>

          <div className="four" data-reveal data-reveal-stagger>
            <FactorCard
              index={0}
              kind="satellite"
              head="The crop, from space"
              lines={
                sat
                  ? [
                      ['How the crop looks', stageWord(sat.stage)],
                      [
                        'Fields past ripening',
                        percent(sat.pct_area_past_maturity),
                      ],
                      [
                        'Picture taken',
                        sat.obs_age_days == null
                          ? '—'
                          : sat.obs_age_days === 0
                            ? 'today'
                            : `${sat.obs_age_days} day${sat.obs_age_days === 1 ? '' : 's'} ago`,
                      ],
                    ]
                  : [['Satellite', 'not available right now']]
              }
              note={
                sat?.stale
                  ? 'Clouds have hidden the fields recently, so this read is older than usual.'
                  : undefined
              }
            />

            <FactorCard
              index={1}
              kind="weather"
              head="The weather on the ground"
              lines={
                weather
                  ? [
                      [
                        'Can you lift the crop',
                        HARVEST_WINDOW[weather.harvest_window] ?? weather.harvest_window,
                      ],
                      [
                        'Will stored crop keep',
                        ROT_RISK[weather.rot_risk] ?? weather.rot_risk,
                      ],
                      [
                        'Dry days in the last two weeks',
                        weather.dry_days_14 == null
                          ? '—'
                          : `${weather.dry_days_14} of ${weather.window_days}`,
                      ],
                    ]
                  : [['Weather', 'not available right now']]
              }
              note={weather?.note}
            />

            <FactorCard
              index={2}
              kind="market"
              head="What the mandi is doing"
              lines={[
                ["Today's rate", perQuintal(alert.score.price_per_quintal)],
                ...alert.score.factors
                  .filter((f) => factorSource(f.feature) === 'market')
                  .slice(0, 2)
                  .map((f) => [sentence(f.phrase), ''] as [string, string]),
              ]}
            />

            <FactorCard
              index={3}
              kind="history"
              head="What happened in past seasons"
              lines={[['Similar weeks since 2016', 'checked against every one']]}
              note={confidenceLine(alert)}
            />
          </div>

          <div className="today__drivers" data-reveal>
            <h3 className="today__drivers-h">
              The things that mattered most today
            </h3>
            <ul className="drivers" data-reveal data-reveal-stagger>
              {alert.score.factors.slice(0, 4).map((f, i) => (
                <li
                  key={f.feature}
                  className="driver"
                  style={{ '--i': i } as React.CSSProperties}
                >
                  <span
                    className={`driver__dot driver__dot--${
                      f.direction === 'raises_sell_pressure' ? 'sell' : 'hold'
                    }`}
                    aria-hidden="true"
                  />
                  <span className="driver__text">{sentence(f.phrase)}</span>
                  <span className="driver__src">{SOURCE_LABEL[factorSource(f.feature)]}</span>
                  <span className="driver__push">
                    {f.direction === 'raises_sell_pressure'
                      ? 'points to selling'
                      : 'points to waiting'}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="section section--white">
        <div className="container inner today__next">
          <div>
            <h2 className="section__title">Check us on any past date</h2>
            <p className="prose">
              Pick a date from any year since 2017 and see what we would have
              said, what the price actually did afterwards, and whether the call
              was right. The wrong ones are in there too.
            </p>
          </div>
          <a className="btn btn--primary" href="#/backtest">
            Check a past date →
          </a>
        </div>
      </section>
    </main>
  )
}

function FactorCard({
  kind,
  head,
  lines,
  note,
  index = 0,
}: {
  kind: string
  head: string
  lines: [string, string][]
  note?: string
  index?: number
}) {
  return (
    <article
      className={`fcard fcard--${kind}`}
      style={{ '--i': index } as React.CSSProperties}
    >
      <h3 className="fcard__head">{head}</h3>
      <dl className="fcard__rows">
        {lines.map(([k, val]) => (
          <div className="fcard__row" key={k}>
            <dt>{k}</dt>
            {val && <dd>{val}</dd>}
          </div>
        ))}
      </dl>
      {note && <p className="fcard__note">{note}</p>}
    </article>
  )
}
