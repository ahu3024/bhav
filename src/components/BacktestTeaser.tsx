/**
 * Landing-page pointer to the backtest. The full time-travel tool lives on its
 * own page — it needs a date picker, a result card, a satellite panel and the
 * misses table, and none of that belongs in the middle of a pitch.
 */
export default function BacktestTeaser() {
  return (
    <section className="section section--white bt-teaser" id="backtest">
      <div className="container inner">
        <div>
          <h2 className="section__title">Don’t take our word for it</h2>
          <p className="prose">
            Pick any day since 2017. We will show you what we would have told
            you that morning, what the rate actually did over the next ten days,
            and whether the call was right. The wrong ones are in there too.
          </p>
        </div>
        <a className="btn btn--primary" href="#/backtest">
          Check a past date →
        </a>
      </div>
    </section>
  )
}
