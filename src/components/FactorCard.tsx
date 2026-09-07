/**
 * One input's read, as a card — the four live signals on the Today page and
 * the three realized outcomes on the backtest page. Same shape either way: a
 * small tag naming the source, a headline, and a list of key/value rows.
 *
 * The rows used to be ruled off from each other with a hairline apiece, which
 * turned every card into a little striped table. They are separated by space
 * and weight now instead, so the card reads as one thing.
 */
const TAG: Record<string, string> = {
  satellite: 'Satellite',
  weather: 'Weather',
  market: 'Mandi',
  history: 'History',
}

export default function FactorCard({
  kind,
  head,
  lines,
  note,
  index = 0,
}: {
  kind: string
  head: string
  lines: [string, string][]
  note?: string
  index?: number
}) {
  return (
    <article
      className={`fcard fcard--${kind}`}
      style={{ '--i': index } as React.CSSProperties}
    >
      <p className="fcard__tag">
        <i aria-hidden="true" />
        {TAG[kind] ?? kind}
      </p>
      <h3 className="fcard__head">{head}</h3>
      <dl className="fcard__rows">
        {lines.map(([k, val]) => (
          <div className="fcard__row" key={k}>
            <dt>{k}</dt>
            {val && <dd>{val}</dd>}
          </div>
        ))}
      </dl>
      {note && <p className="fcard__note">{note}</p>}
    </article>
  )
}
