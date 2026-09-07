import { sources } from '../data'

export default function SourceStrip() {
  return (
    <div className="source-strip">
      <div className="container source-strip__inner" data-reveal data-reveal-stagger>
        {sources.map((s, i) => (
          <div key={s.label} style={{ '--i': i } as React.CSSProperties}>
            <div className="source__label">{s.label}</div>
            <div className="source__desc">{s.desc}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
