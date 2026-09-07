import FieldRaster from './FieldRaster'
import SignalCard from './SignalCard'

export default function Hero() {
  return (
    <section className="hero" id="top">
      <div className="container hero__inner">
        <div className="hero__copy">
          <p className="eyebrow">— Data from the field —</p>
          <h1 className="hero__title">
            Sell now, or wait?{' '}
            <span className="accent">We’ll tell you which.</span>
          </h1>
          <p className="hero__lead">
            Bhav looks at your crop from space, the weather on your fields, and
            what onion is fetching in the mandi — then compares all of it against
            nine years of past seasons. You get one answer: sell now or wait, and
            what that choice is worth in rupees per quintal.
          </p>
          <div className="hero__cta">
            <a className="btn btn--live" href="#/today">
              <span className="btn__pulse" aria-hidden="true" />
              What’s the call today?
            </a>
            <a className="btn btn--outline" href="#/backtest">
              Check a past date
            </a>
          </div>
        </div>

        <div className="hero__media">
          <div className="media-frame">
            <FieldRaster />
            <span className="media-frame__tag">Onion fields near Nashik, seen from space</span>
          </div>
          <SignalCard />
        </div>
      </div>
    </section>
  )
}
