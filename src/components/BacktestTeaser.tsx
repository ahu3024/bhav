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
          <h2 className="section__title">Don’t take our word for it. Rewind it.</h2>
          <p className="prose">
            Pick any date since 2017 and see the alert that would have fired, the
            price move that actually followed, and whether the call held up —
            graded against the habit it argues against. The misses are in there
            too, on the same page.
          </p>
        </div>
        <a className="btn btn--primary" href="#/backtest">
          Open the backtest →
        </a>
      </div>
    </section>
  )
}
