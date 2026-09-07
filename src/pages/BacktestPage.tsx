import { useEffect, useState } from 'react'
import { useReveal } from '../useReveal'
import FactorCard from '../components/FactorCard'
import VerdictBanner from '../components/VerdictBanner'
import DateField, { type Preset } from '../components/DateField'
import OutcomeCompare from '../components/OutcomeCompare'
import { Section, SectionHead } from '../components/Section'
import {
  getBacktest,
  getNdviAsOf,
  getWeatherAsOf,
  friendlyError,
  type Alert,
  type Backtest,
  type NdviRead,
  type WeatherRead,
} from '../api'
import { stageWord, HARVEST_WINDOW, ROT_RISK, perQuintal, percent } from '../plain'

// Agmarknet history starts 2016-01; the seasonal features need ~a year of
// warm-up, and the label needs 10 days of future prices at the other end.
const MIN_DATE = '2017-03-01'
const MAX_DATE = new Date(Date.now() - 14 * 864e5).toISOString().slice(0, 10)

// The three sharpest 10-day falls in the price series actually loaded, one per
// year. Taken from the data rather than from headlines: quoting a real-world
// record the loaded series does not contain is the fastest way to lose a room.
const PRESETS: Preset[] = [
  { date: '2019-04-17', label: 'April 2019', note: 'rate fell by a third in ten days' },
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
  const showing = a && r && o && state !== 'error'

  return (
    <main className={`page page--backtest${state === 'loading' ? ' is-busy' : ''}`}>
      {/* The picker is the page's headline, not a form bolted above one — so
          the title, the control and the presets are one block, and the answer
          starts the moment it ends. */}
      <Section size="sm" className="bt-head">
        <div className="bt-head__copy">
          <p className="eyebrow">— Check our record —</p>
          <h1 className="bt-head__title">Pick any past day</h1>
          <p className="prose">
            We rebuild the call from what was known that morning — nothing after
            it — then show what the mandi actually did next.
          </p>
        </div>

        <DateField
          value={date}
          min={MIN_DATE}
          max={MAX_DATE}
          busy={state === 'loading'}
          presets={PRESETS}
          onChange={setDate}
          onRun={(d) => void run(d)}
        />

        {state === 'error' && <p className="bt-err">{err}</p>}
      </Section>

      {/* keyed by date so every new pick remounts this whole block — the
          reveal and count-up animations replay instead of sitting static */}
      {showing && <Result key={a.date} a={a} r={r} o={o} ndvi={ndvi} wx={wx} />}
    </main>
  )
}

function Result({
  a,
  r,
  o,
  ndvi,
  wx,
}: {
  a: Alert
  r: Backtest['realized']
  o: Backtest['outcome']
  ndvi: NdviRead | null
  wx: WeatherRead | null
}) {
  return (
    <>
      {/* the answer, in exactly the shape the live page uses */}
      <VerdictBanner
        color={a.color}
        date={a.date}
        heading="h2"
        reason={a.reason}
        aside={
          <OutcomeCompare
            ours={o.strategy_price_per_quintal}
            oursNote={o.action}
            theirs={o.baseline_price_per_quintal}
            theirsNote={o.baseline_label}
            delta={o.delta_per_quintal}
            right={o.call_was_right}
          />
        }
      />

      <Section size="lg" lift>
        <SectionHead
          eyebrow="What was on the table"
          title="The reads behind that call"
          lead="The same three inputs the live page shows, frozen at that morning — and what the mandi did over the days that followed."
        />

        <div className="card-grid" data-reveal data-reveal-stagger>
          <FactorCard
            index={0}
            kind="market"
            head="What the mandi did next"
            lines={[
              ['Rate that day', perQuintal(r.price_now)],
              [
                `Lowest over the next ${r.horizon_days} days`,
                r.price_min == null ? '—' : perQuintal(r.price_min),
              ],
              [
                'Which was a move of',
                r.max_drop_pct == null
                  ? '—'
                  : `${r.max_drop_pct <= 0 ? 'down' : 'up'} ${percent(Math.abs(r.max_drop_pct), 1)}`,
              ],
            ]}
          />

          {ndvi && (
            <FactorCard
              index={1}
              kind="satellite"
              head="The crop, from space"
              lines={[
                ['The crop was', stageWord(ndvi.stage)],
                ['Fields past ripening', percent(ndvi.pct_area_past_maturity)],
                [
                  'Satellite picture was',
                  ndvi.obs_age_days == null
                    ? '—'
                    : `${ndvi.obs_age_days} day${ndvi.obs_age_days === 1 ? '' : 's'} old`,
                ],
              ]}
              note={ndvi.stale ? 'Clouds had hidden the fields around this date.' : undefined}
            />
          )}

          {wx && (
            <FactorCard
              index={2}
              kind="weather"
              head="The weather on the ground"
              lines={[
                ['Could you lift the crop', HARVEST_WINDOW[wx.harvest_window] ?? wx.harvest_window],
                ['Would stored crop keep', ROT_RISK[wx.rot_risk] ?? wx.rot_risk],
                [
                  'Dry days in that fortnight',
                  wx.dry_days_14 == null ? '—' : `${wx.dry_days_14} of ${wx.window_days}`,
                ],
              ]}
              note={wx.note}
            />
          )}
        </div>
      </Section>
    </>
  )
}
