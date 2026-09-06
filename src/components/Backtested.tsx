import { fingerprint } from '../data'

export default function Backtested() {
  return (
    <section className="section section--white backtest" id="backtest">
      <div className="container inner">
        <div>
          <h2 className="section__title">
            Every signal is backtested. Every pattern is named.
          </h2>
          <p className="prose">
            Signal 104 isn't a black box number. It maps to: Nashik Onion, September
            Week 1, NDVI rising, arrivals below median, 3-day price flat. This exact
            fingerprint matched 14 historical weeks. In 11 of those, prices rose
            within 6 days. That's what the 78% means.
          </p>
        </div>

        <dl className="fingerprint">
          <div className="fingerprint__id">{fingerprint.id}</div>
          <div className="sc__hr" />
          <div className="fingerprint__rows">
            {fingerprint.rows.map((r) => (
              <div className="fp-row" key={r.k}>
                <dt>{r.k}</dt>
                <dd className={r.hot ? 'hot' : r.mono ? 'mono' : undefined}>{r.v}</dd>
              </div>
            ))}
          </div>
        </dl>
      </div>
    </section>
  )
}
