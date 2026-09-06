import { useState } from 'react'
import { getBacktest, formatDate, type Backtest } from '../api'

const COLOR_WORD: Record<string, string> = {
  RED: 'Sell now',
  AMBER: 'Caution',
  GREEN: 'Wait',
}

// Data covers 2016-01 onward; leave room for warm-up and the 10-day horizon.
const MIN_DATE = '2017-06-01'
const MAX_DATE = new Date(Date.now() - 14 * 864e5).toISOString().slice(0, 10)

function rupee(n: number): string {
  const s = Math.round(Math.abs(n)).toLocaleString('en-IN')
  return `${n < 0 ? '−' : ''}₹${s}`
}

export default function Backtested() {
  const [date, setDate] = useState('2024-04-05')
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [res, setRes] = useState<Backtest | null>(null)
  const [err, setErr] = useState('')

  async function run() {
    setState('loading')
    setErr('')
    try {
      setRes(await getBacktest(date))
      setState('idle')
    } catch (e) {
      setErr(
        e instanceof Error && e.message.includes('Failed to fetch')
          ? 'Backend not reachable — start it with `uvicorn bhav.api:app` on :8000.'
          : String(e),
      )
      setState('error')
    }
  }

  const a = res?.alert
  const r = res?.realized
  const o = res?.outcome

  return (
    <section className="section section--white backtest" id="backtest">
      <div className="container inner">
        <div>
          <h2 className="section__title">
            Pick any past date. See what Bhav would have said — and what the
            market actually did.
          </h2>
          <p className="prose">
            Same scoring code as the live signal, just rewound to the date you
            choose. No cherry-picked wins: the outcome below is the real price
            move over the next 10 days, priced in ₹/quintal against the habit the
            alert argues against.
          </p>
        </div>

        <div className="bt-panel">
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
            <button className="bt-run" onClick={run} disabled={state === 'loading'}>
              {state === 'loading' ? 'Running…' : 'Run backtest'}
            </button>
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
                  <dd className={r.max_drop_pct != null && r.max_drop_pct <= -0.1 ? 'hot' : 'mono'}>
                    {r.max_drop_pct != null ? `${(r.max_drop_pct * 100).toFixed(1)}%` : '—'}
                  </dd>
                </div>
                <div className="fp-row">
                  <dt>Followed Bhav — {o.action}</dt>
                  <dd className="mono">{rupee(o.strategy_price_per_quintal)}/qtl</dd>
                </div>
                <div className="fp-row">
                  <dt>Instead of — {o.baseline_label}</dt>
                  <dd className="mono">{rupee(o.baseline_price_per_quintal)}/qtl</dd>
                </div>
              </div>

              <div className="bt-verdict">
                <div>
                  <span className="bt-delta">
                    {o.delta_per_quintal >= 0 ? '+' : ''}
                    {rupee(o.delta_per_quintal)}/qtl
                  </span>
                  <span className="bt-delta-pct">
                    {' '}({(o.delta_pct * 100).toFixed(1)}%)
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

          {state === 'idle' && !res && (
            <p className="bt-msg">
              Try <button className="bt-link" onClick={() => setDate('2024-04-05')}>
                2024-04-05
              </button>{' '}
              — a harvest-glut crash.
            </p>
          )}
        </div>
      </div>
    </section>
  )
}
