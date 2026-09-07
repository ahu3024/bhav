/**
 * The month calendar that drops out of the date field.
 *
 * The browser's own date popover is chrome — it cannot be styled, it looks
 * different on every machine, and on this site it looked like a stray dialog
 * from another program. So the grid is ours: same type, same radii, same
 * greens as the rest of the page, and wide enough to hit with a thumb.
 *
 * Everything is computed in UTC from `YYYY-MM-DD` strings. A local Date would
 * quietly shift a day across a timezone boundary, and "the 17th" has to mean
 * the 17th.
 */
import { useEffect, useMemo, useRef, useState } from 'react'

const DOW = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

const pad = (n: number) => String(n).padStart(2, '0')
const iso = (y: number, m: number, d: number) => `${y}-${pad(m + 1)}-${pad(d)}`
const daysIn = (y: number, m: number) => new Date(Date.UTC(y, m + 1, 0)).getUTCDate()
const firstDow = (y: number, m: number) => new Date(Date.UTC(y, m, 1)).getUTCDay()
const todayIso = () => new Date().toISOString().slice(0, 10)

/** Clamp an ISO day into [min, max] — string compare is safe on ISO dates. */
const clamp = (d: string, min: string, max: string) =>
  d < min ? min : d > max ? max : d

export default function Calendar({
  value,
  min,
  max,
  onPick,
  onClose,
}: {
  value: string
  min: string
  max: string
  onPick: (d: string) => void
  onClose: () => void
}) {
  const [vy, setVy] = useState(() => Number(value.slice(0, 4)))
  const [vm, setVm] = useState(() => Number(value.slice(5, 7)) - 1)
  // The day the arrow keys are sitting on, which is not the same as the day
  // that is chosen — you move around the month before committing to one.
  const [cursor, setCursor] = useState(value)
  const grid = useRef<HTMLDivElement>(null)
  const root = useRef<HTMLDivElement>(null)

  const minY = Number(min.slice(0, 4))
  const maxY = Number(max.slice(0, 4))
  const years = useMemo(
    () => Array.from({ length: maxY - minY + 1 }, (_, i) => minY + i),
    [minY, maxY],
  )

  const today = todayIso()

  // The month's cells, with blanks for the days before the 1st so the columns
  // line up under their weekday.
  const cells = useMemo(() => {
    const out: (string | null)[] = Array(firstDow(vy, vm)).fill(null)
    for (let d = 1; d <= daysIn(vy, vm); d++) out.push(iso(vy, vm, d))
    return out
  }, [vy, vm])

  // Close on Escape or on a click that lands outside the popover.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) onClose()
    }
    document.addEventListener('keydown', onKey, true)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.removeEventListener('mousedown', onDown)
    }
  }, [onClose])

  // Open with the chosen day focused, so the keyboard lands somewhere useful.
  useEffect(() => {
    grid.current?.querySelector<HTMLButtonElement>('[data-focus="1"]')?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** Move the arrow-key cursor by `n` days, following it to the new month. */
  function move(n: number) {
    const next = clamp(
      new Date(Date.parse(`${cursor}T00:00:00Z`) + n * 864e5).toISOString().slice(0, 10),
      min,
      max,
    )
    setCursor(next)
    setVy(Number(next.slice(0, 4)))
    setVm(Number(next.slice(5, 7)) - 1)
    // The grid re-renders around the new cursor, so focus has to follow it.
    requestAnimationFrame(() =>
      grid.current?.querySelector<HTMLButtonElement>('[data-focus="1"]')?.focus(),
    )
  }

  function shiftMonth(n: number) {
    const m = vm + n
    const y = vy + Math.floor(m / 12)
    setVy(y)
    setVm(((m % 12) + 12) % 12)
  }

  // A month is off the end if every one of its days is outside the range.
  const prevOff = iso(vy, vm, 1) <= min
  const nextOff = iso(vy, vm, daysIn(vy, vm)) >= max

  return (
    <div
      className="cal"
      ref={root}
      role="dialog"
      aria-label="Choose a date"
      onKeyDown={(e) => {
        const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key]
        if (step) {
          e.preventDefault()
          move(step)
        } else if (e.key === 'PageUp' || e.key === 'PageDown') {
          e.preventDefault()
          shiftMonth(e.key === 'PageUp' ? -1 : 1)
        }
      }}
    >
      <div className="cal__head">
        <button
          type="button"
          className="cal__nav"
          aria-label="Previous month"
          disabled={prevOff}
          onClick={() => shiftMonth(-1)}
        >
          ‹
        </button>

        <div className="cal__pickers">
          <label className="cal__sel">
            <select value={vm} onChange={(e) => setVm(Number(e.target.value))}>
              {MONTHS.map((name, i) => (
                <option key={name} value={i}>
                  {name}
                </option>
              ))}
            </select>
            <span aria-hidden="true">{MONTHS[vm]}</span>
          </label>
          <label className="cal__sel">
            <select value={vy} onChange={(e) => setVy(Number(e.target.value))}>
              {years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
            <span aria-hidden="true">{vy}</span>
          </label>
        </div>

        <button
          type="button"
          className="cal__nav"
          aria-label="Next month"
          disabled={nextOff}
          onClick={() => shiftMonth(1)}
        >
          ›
        </button>
      </div>

      <div className="cal__dows" aria-hidden="true">
        {DOW.map((d, i) => (
          <span key={i}>{d}</span>
        ))}
      </div>

      <div className="cal__grid" ref={grid} role="grid">
        {cells.map((d, i) =>
          d == null ? (
            <span key={`b${i}`} className="cal__blank" />
          ) : (
            <button
              key={d}
              type="button"
              className={[
                'cal__day',
                d === value ? 'is-sel' : '',
                d === today ? 'is-today' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              disabled={d < min || d > max}
              aria-current={d === value ? 'date' : undefined}
              data-focus={d === cursor ? '1' : undefined}
              tabIndex={d === cursor ? 0 : -1}
              onClick={() => onPick(d)}
            >
              {Number(d.slice(8))}
            </button>
          ),
        )}
      </div>

      <div className="cal__foot">
        <span className="cal__range">
          {MONTHS[Number(min.slice(5, 7)) - 1].slice(0, 3)} {min.slice(0, 4)} — today
        </span>
        <button
          type="button"
          className="cal__latest"
          onClick={() => onPick(max)}
          disabled={value === max}
        >
          Jump to the latest day
        </button>
      </div>
    </div>
  )
}
