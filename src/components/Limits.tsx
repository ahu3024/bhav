import { limits } from '../data'

export default function Limits() {
  return (
    <section className="section limits" id="limits">
      <div className="container inner">
        <h2 className="section__title">What Bhav cannot do</h2>
        <div className="limits__grid" data-reveal data-reveal-stagger>
          {limits.map((l, i) => (
            <div key={l.h} style={{ '--i': i } as React.CSSProperties}>
              <h3 className="limit__h">{l.h}</h3>
              <p className="limit__p">{l.p}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
