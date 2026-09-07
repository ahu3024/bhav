/**
 * The numbers a farmer checks second — best days, today's rate, how often the
 * pattern held. A list of rows, some of which carry a 0–100 bar. Sits inside
 * the verdict banner and hangs below its edge, which is what ties the banner
 * to the section underneath.
 */
export type GlanceRow = {
  k: string
  v: string
  /** 0–100; draws a meter under the row. */
  bar?: number
}

export default function GlancePanel({
  title,
  rows,
}: {
  title?: string
  rows: GlanceRow[]
}) {
  return (
    <aside className="glance">
      {title && <p className="glance__title">{title}</p>}
      {rows.map((r, i) => (
        <div className="glance__row" key={r.k} style={{ '--i': i } as React.CSSProperties}>
          <span className="glance__k">{r.k}</span>
          <span className="glance__v">{r.v}</span>
          {r.bar != null && (
            <span className="glance__bar" aria-hidden="true">
              <i style={{ width: `${Math.max(0, Math.min(100, r.bar))}%` }} />
            </span>
          )}
        </div>
      ))}
    </aside>
  )
}
