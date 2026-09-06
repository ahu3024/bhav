import { signal } from '../data'

export default function SignalCard() {
  return (
    <article className="signal-card" aria-label="Sample Bhav signal">
      <div className="sc__row sc__head">
        <span className="sc__meta">{signal.ref}</span>
        <span className="sc__meta">{signal.date}</span>
      </div>

      <div className="sc__title">{signal.market}</div>
      <div className="sc__hr" />

      <div className="sc__row sc__action">
        <span className="sc__action-left">
          <span className="sc__k">Action</span>
          <span className="sc__verdict">{signal.action}</span>
        </span>
        <span className="sc__price">{signal.price}</span>
      </div>

      <div className="sc__factors">
        {signal.factors.map((f) => (
          <div className="sc__factor" key={f.text}>
            <span>{f.text}</span>
            <span>{f.src}</span>
          </div>
        ))}

        <div className="sc__conf">
          <div className="sc__conf-row">
            <b>{signal.confidence}% confidence</b>
            <span>P(UP)</span>
          </div>
          <div className="sc__bar">
            <i style={{ width: `${signal.confidence}%` }} />
          </div>
        </div>
      </div>

      <span className="sc__foot">{signal.foot}</span>
    </article>
  )
}
