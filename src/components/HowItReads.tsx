import { steps } from '../data'

export default function HowItReads() {
  return (
    <section className="section how" id="how">
      <div className="container inner">
        <h2 className="section__title">How we work out the answer</h2>
        <div className="steps" data-reveal data-reveal-stagger>
          {steps.map((s, i) => (
            <div className="step" key={s.n} style={{ '--i': i } as React.CSSProperties}>
              <div className="step__n">{s.n}</div>
              <div>
                <div className="step__label">{s.label}</div>
                <p className="step__desc">{s.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
