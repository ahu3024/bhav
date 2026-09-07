import { useEffect, useRef, useState } from 'react'

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

/**
 * Count up to `target` rather than just displaying it — a figure that arrives
 * mid-motion reads as live and is worth a second look; one that is simply
 * printed on the page is easy to skim past. Re-runs whenever `target` changes,
 * which is exactly once in practice (the moment real data replaces the 0 a
 * page opens with), so this reads as "the number settling in" rather than a
 * tic. Skips straight to the answer under reduced motion, same as useReveal.
 */
export function useCountUp(target: number, ms = 900): number {
  const [n, setN] = useState(0)
  const from = useRef(0)

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduced || target === from.current) {
      setN(target)
      from.current = target
      return
    }
    const start0 = from.current
    const t0 = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - t0) / ms)
      const eased = 1 - Math.pow(1 - t, 3) // ease-out cubic — a settle, not a snap
      setN(Math.round(start0 + (target - start0) * eased))
      if (t < 1) raf = requestAnimationFrame(tick)
      else from.current = target
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])

  return n
}
