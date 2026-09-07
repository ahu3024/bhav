import { useEffect } from 'react'

/**
 * Reveal-on-scroll, once per element.
 *
 * Anything marked `data-reveal` starts translated down and transparent, and is
 * un-hidden the first time it crosses into view. One observer for the whole
 * document rather than a hook per component, so adding motion to a section is
 * an attribute rather than a wiring job.
 *
 * Two things keep it honest: elements already on screen at mount are revealed
 * immediately (no first-paint flash of empty page), and if the browser cannot
 * observe — or the reader asked for less motion — everything is shown at once.
 */
export function useReveal(deps: unknown[] = []) {
  useEffect(() => {
    const nodes = Array.from(
      document.querySelectorAll<HTMLElement>('[data-reveal]:not(.is-revealed)'),
    )
    if (!nodes.length) return

    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduced || typeof IntersectionObserver === 'undefined') {
      nodes.forEach((n) => n.classList.add('is-revealed'))
      return
    }

    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting) return
          e.target.classList.add('is-revealed')
          io.unobserve(e.target)
        })
      },
      // Fire a little before the element is fully in view, so the motion has
      // finished by the time it is actually being read.
      { rootMargin: '0px 0px -12% 0px', threshold: 0.05 },
    )

    nodes.forEach((n) => io.observe(n))
    return () => io.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}
