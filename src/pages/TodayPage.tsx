import { useReveal, useCountUp } from '../useReveal'
import FactorCard from '../components/FactorCard'
import VerdictBanner from '../components/VerdictBanner'
import GlancePanel, { type GlanceRow } from '../components/GlancePanel'
import DriverList from '../components/DriverList'
import { Section, SectionHead } from '../components/Section'
import { useSnapshot, formatDate, type Alert } from '../api'
import {
  stageWord,
  HARVEST_WINDOW,
  ROT_RISK,
  rupees,
  perQuintal,
  percent,
  worthLine,
  confidenceLine,
  factorSource,
  sentence,
} from '../plain'

export default function TodayPage() {
  // One cached response for the whole page, shared with the landing page — so
  // arriving here from there is instant and costs no request at all.
  const { data: snap, error } = useSnapshot()
  const alert: Alert | null = snap?.alert ?? null
  // Context, never the verdict: a missing panel must not blank the page, which
  // is why /snapshot reports a failed section as null beside the rest.
  const ndvi = snap?.ndvi ?? null
  const wx = snap?.weather ?? null
  const err = error ?? ''

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

  if (err || !alert || !worth) {
    return (
      <main className="page">
        <Section size="lg">
          <div className="page-state">
            <p className="eyebrow">Today’s call</p>
            <h1 className="page-state__title">
              {err ? 'That did not load' : 'Reading today’s data'}
            </h1>
            <p className="prose">
              {err || 'Checking the latest satellite pass, the weather on the ground and this morning’s mandi rate…'}
            </p>
            {!err && (
              <span className="page-state__bar" aria-hidden="true">
                <i />
              </span>
            )}
          </div>
        </Section>
      </main>
    )
  }

  const sat = ndvi?.current
  const weather = wx?.current
  const waiting = alert.color === 'GREEN'

  const glance: GlanceRow[] = [
    {
      k: 'Best days to sell',
      v: `${formatDate(alert.window_start)} — ${formatDate(alert.window_end)}`,
    },
    { k: 'Rate in the mandi today', v: perQuintal(alert.score.price_per_quintal) },
    {
      k: 'How often this pattern held',
      v: `${animatedConfidence} out of 100 weeks`,
      bar: animatedConfidence,
    },
    ...(sat ? [{ k: 'The crop right now', v: stageWord(sat.stage) }] : []),
  ]

  return (
    <main className="page page--today">
      {/* ---- the answer, before anything else ---- */}
      <VerdictBanner
        color={alert.color}
        date={alert.date}
        waiting={waiting}
        aside={<GlancePanel title="At a glance" rows={glance} />}
      >
        <p className="verdict__money">
          <span className="verdict__amount">
            {worth.prefix}
            {rupees(animatedWorth)}
            {worth.suffix}
          </span>
          <span className="verdict__caption">{worth.caption}</span>
        </p>

        {/* "Wait" is an ongoing state, not a one-off verdict — say so, so the
            banner reads as a thing still in motion rather than a dead end. */}
        {waiting && (
          <p className="verdict__watch">
            <span className="verdict__watch-dot" aria-hidden="true" />
            Still watching, every day — your weekly WhatsApp alert will say the
            moment this changes
          </p>
        )}
      </VerdictBanner>

      {/* ---- why ---- */}
      <Section size="lg" lift>
        <SectionHead
          eyebrow="The reasoning"
          title="Why we’re saying this"
          lead={`Four things go into every call. Here is what each one looked like today, against a mandi rate of ${perQuintal(alert.score.price_per_quintal)}.`}
        />

        <div className="card-grid" data-reveal data-reveal-stagger>
          <FactorCard
            index={0}
            kind="satellite"
            head="The crop, from space"
            lines={
              sat
                ? [
                    ['How the crop looks', stageWord(sat.stage)],
                    ['Fields past ripening', percent(sat.pct_area_past_maturity)],
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

        <div className="drivers-block" data-reveal>
          <h3 className="drivers-block__h">The things that mattered most today</h3>
          <DriverList factors={alert.score.factors} />
        </div>
      </Section>

      {/* ---- where to go next ---- */}
      <Section size="md">
        <div className="cta-panel" data-reveal>
          <div className="cta-panel__copy">
            <h2 className="cta-panel__title">Check us on any past date</h2>
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
      </Section>
    </main>
  )
}
