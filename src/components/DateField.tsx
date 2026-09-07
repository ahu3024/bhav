/**
 * The date control for the backtest page.
 *
 * A native `<input type="date">` is a 150px box with an 11px glyph, and the
 * calendar it drops is browser chrome — unstyleable, different on every
 * machine, and on this page it read as a dialog from another program. So the
 * field is rendered at headline scale and it opens our own month grid (see
 * Calendar), which shares the site's type, radii and greens.
 */
import { useRef, useState } from 'react'
import Calendar from './Calendar'

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

/** Shift an ISO day by `n` days, staying in UTC so DST never moves the date. */
function shift(iso: string, n: number): string {
  const t = Date.parse(`${iso}T00:00:00Z`)
  return new Date(t + n * 864e5).toISOString().slice(0, 10)
}

export type Preset = { date: string; label: string; note: string }

export default function DateField({
  value,
  min,
  max,
  onChange,
  onRun,
  busy = false,
  presets = [],
}: {
  value: string
  min: string
  max: string
  onChange: (d: string) => void
  onRun: (d: string) => void
  busy?: boolean
  presets?: Preset[]
}) {
  const [open, setOpen] = useState(false)
  const face = useRef<HTMLButtonElement>(null)
  const [y, m, d] = value.split('-').map(Number)
  const weekday = DAYS[new Date(Date.parse(`${value}T00:00:00Z`)).getUTCDay()]

  const pick = (next: string) => {
    onChange(next)
    onRun(next)
  }

  const step = (n: number) => {
    const next = shift(value, n)
    if (next < min || next > max) return
    pick(next)
  }

  return (
    <div className="dpick">
      <div className="dpick__bar">
        <button
          type="button"
          className="dpick__step"
          aria-label="Previous day"
          disabled={shift(value, -1) < min}
          onClick={() => step(-1)}
        >
          ‹
        </button>

        <div className="dpick__field">
          <button
            type="button"
            ref={face}
            className={`dpick__face${open ? ' is-open' : ''}`}
            aria-haspopup="dialog"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <span className="dpick__label">Pick a day</span>
            <span className="dpick__date">
              <b>{d}</b> {MONTHS[m - 1]} {y}
            </span>
            <span className="dpick__day">
              {weekday}
              <span className="dpick__hint">
                {open ? 'choose a day below' : 'tap to open the calendar'}
              </span>
            </span>

            {/* the field is far wider than the date needs — a calendar mark on
                the far side says what it is, rather than a long empty tail */}
            <svg className="dpick__cal" viewBox="0 0 24 24" aria-hidden="true">
              <rect x="3" y="5" width="18" height="16" rx="3" />
              <path d="M3 10h18M8 3v4M16 3v4" />
              <circle cx="8.5" cy="14.5" r="1.15" className="dpick__cal-dot" />
            </svg>
          </button>

          {open && (
            <Calendar
              value={value}
              min={min}
              max={max}
              onPick={(next) => {
                setOpen(false)
                face.current?.focus()
                if (next !== value) pick(next)
              }}
              onClose={() => {
                setOpen(false)
                face.current?.focus()
              }}
            />
          )}
        </div>

        <button
          type="button"
          className="dpick__step"
          aria-label="Next day"
          disabled={shift(value, 1) > max}
          onClick={() => step(1)}
        >
          ›
        </button>

        <button
          type="button"
          className="dpick__go"
          onClick={() => onRun(value)}
          disabled={busy}
        >
          {busy ? 'Checking…' : 'Show me'}
        </button>
      </div>

      {presets.length > 0 && (
        <div className="dpick__presets">
          <span className="dpick__presets-k">Or jump to a day the rate fell hard</span>
          <div className="dpick__chips">
            {presets.map((p) => (
              <button
                key={p.date}
                type="button"
                className={`chip${p.date === value ? ' is-on' : ''}`}
                onClick={() => pick(p.date)}
              >
                <b>{p.label}</b>
                <span>{p.note}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
