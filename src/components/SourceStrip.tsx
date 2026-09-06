import { sources } from '../data'

export default function SourceStrip() {
  return (
    <div className="source-strip">
      <div className="container source-strip__inner">
        {sources.map((s) => (
          <div key={s.label}>
            <div className="source__label">{s.label}</div>
            <div className="source__desc">{s.desc}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
