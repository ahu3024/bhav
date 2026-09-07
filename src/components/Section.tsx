/**
 * Page primitives.
 *
 * The pages used to be built out of full-bleed bands that alternated white and
 * off-white, each one fenced by a hairline top and bottom. Read top to bottom
 * that is a stack of stripes, not a page — every block announced itself as a
 * separate thing. These primitives replace that: one continuous ground, with
 * vertical rhythm and elevation doing the separating instead of rules.
 */
import type { ReactNode } from 'react'

/** A block of page content. No background, no borders — just rhythm. */
export function Section({
  id,
  tone = 'plain',
  size = 'md',
  lift = false,
  className = '',
  children,
}: {
  id?: string
  /** `well` sinks the block slightly into the ground; `plain` leaves it flat. */
  tone?: 'plain' | 'well'
  size?: 'sm' | 'md' | 'lg'
  /** Pull the block up so it overlaps whatever sits above it. */
  lift?: boolean
  className?: string
  children: ReactNode
}) {
  return (
    <section
      id={id}
      className={[
        'sec',
        `sec--${size}`,
        tone === 'well' ? 'sec--well' : '',
        lift ? 'sec--lift' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <div className="container sec__inner">{children}</div>
    </section>
  )
}

/** Eyebrow + title + optional lead, spaced as one unit. */
export function SectionHead({
  eyebrow,
  title,
  lead,
  aside,
}: {
  eyebrow?: string
  title: ReactNode
  lead?: ReactNode
  aside?: ReactNode
}) {
  return (
    <header className="sec-head" data-reveal>
      <div className="sec-head__copy">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h2 className="sec-head__title">{title}</h2>
        {lead && <p className="prose">{lead}</p>}
      </div>
      {aside && <div className="sec-head__aside">{aside}</div>}
    </header>
  )
}
