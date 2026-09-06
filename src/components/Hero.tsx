import FieldRaster from './FieldRaster'
import SignalCard from './SignalCard'

export default function Hero() {
  return (
    <section className="hero" id="top">
      <div className="container hero__inner">
        <div className="hero__copy">
          <p className="eyebrow">— Data from the field —</p>
          <h1 className="hero__title">
            We see the harvest coming{' '}
            <span className="accent">before the market does.</span>
          </h1>
          <p className="hero__lead">
            Crop conditions, mandi prices, and 9 years of history — compressed into
            one signal a smallholder can act on: sell now or wait. Every alert is
            pattern-backed with what actually happened in past seasons — and priced
            in ₹/quintal.
          </p>
          <div className="hero__cta">
            <a className="btn btn--primary" href="#backtest">
              Run a past week
            </a>
            <a className="btn btn--outline" href="#how">
              See the pipeline
            </a>
          </div>
        </div>

        <div className="hero__media">
          <div className="media-frame">
            <FieldRaster />
            <span className="media-frame__tag">Sentinel-2 · NDVI · Nashik · 06 Sep</span>
          </div>
          <SignalCard />
        </div>
      </div>
    </section>
  )
}
