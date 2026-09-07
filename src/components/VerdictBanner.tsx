/**
 * The verdict, as loud as it gets — one component, used by both the live page
 * and the backtest page so a past call is presented in exactly the same shape
 * as today's. The tint is painted as a wash that dissolves into the page
 * ground at the bottom rather than ending on a hairline, so whatever follows
 * reads as the same page continuing rather than the next stripe down.
 */
import type { ReactNode } from 'react'
import { VERDICT, sentence } from '../plain'
import { formatDate } from '../api'

export default function VerdictBanner({
  color,
  date,
  place = 'Onion · Nashik',
  reason,
  heading = 'h1',
  waiting = false,
  children,
  aside,
}: {
  color: string
  date: string
  place?: string
  /** Overrides the stock line for this colour — the backtest's actual reason. */
  reason?: string
  heading?: 'h1' | 'h2'
  waiting?: boolean
  children?: ReactNode
  aside?: ReactNode
}) {
  const v = VERDICT[color] ?? { word: color, line: '' }
  const tone = color.toLowerCase()
  const Word = heading

  return (
    <section
      className={`verdict verdict--${tone}${waiting ? ' verdict--waiting' : ''}`}
    >
      <div className="container verdict__grid">
        <div className="verdict__main">
          <p className="verdict__where">
            {place} · {formatDate(date)}
          </p>
          <Word className="verdict__word">{v.word}</Word>
          <p className="verdict__line">{reason ? sentence(reason) : v.line}</p>
          {children}
        </div>
        {aside && <div className="verdict__aside">{aside}</div>}
      </div>
    </section>
  )
}
