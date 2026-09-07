import { useEffect, useState } from 'react'

/**
 * Hash routing, ~30 lines, no dependency.
 *
 * Hash rather than history routing because the site ships as static files: a
 * deep link like /backtest would 404 on any host that isn't rewriting to
 * index.html, whereas #/backtest survives `vite preview`, GitHub Pages, and a
 * file:// open of dist/. In-page anchors (#how, #limits) keep working — they
 * simply don't start with `#/`.
 */

export type Route = '/' | '/today' | '/backtest'

function parse(hash: string): Route {
  const path = hash.replace(/^#/, '')
  if (path.startsWith('/backtest')) return '/backtest'
  if (path.startsWith('/today')) return '/today'
  return '/'
}

/**
 * The in-page anchor a hash names, if it names one: `#how` → `how`, `#/today`
 * → null. Anchors resolve to the landing route above, so these are always
 * landing-page sections.
 */
function parseAnchor(hash: string): string | null {
  const path = hash.replace(/^#/, '')
  return path && !path.startsWith('/') ? path : null
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash))

  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return route
}

/**
 * Put the reader where the hash says they should be: the top of a page route,
 * or the section an anchor names.
 *
 * The browser can't do the anchor case for us here. It scrolls the moment the
 * hash changes, which on a jump in from another page (#/today → #how) is before
 * React has rendered the landing page the target lives on — so it finds
 * nothing and gives up. Same story on a cold load of a shared #how link.
 */
export function useRouteScroll(route: Route) {
  useEffect(() => {
    const anchor = parseAnchor(window.location.hash)
    if (!anchor) {
      window.scrollTo(0, 0)
      return
    }

    // 'instant', not 'auto' — 'auto' hands the decision back to the page's
    // `scroll-behavior: smooth`, which would try to glide the reader all the
    // way down a page they have not seen yet. The section should just be there.
    const align = () =>
      document.getElementById(anchor)?.scrollIntoView({ behavior: 'instant' })
    align()

    // The satellite and weather panels sit above most of these sections and
    // swap a one-line "loading" for a full chart when their data lands, which
    // pushes the target down after we have already jumped. So hold the section
    // under the reader while the page settles — until they scroll themselves,
    // or two seconds, whichever comes first.
    let stopped = false
    const stop = () => {
      if (stopped) return
      stopped = true
      ro?.disconnect()
      clearTimeout(timer)
      gestures.forEach((g) => window.removeEventListener(g, stop))
    }
    const ro =
      typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => align())
    ro?.observe(document.body)
    const timer = setTimeout(stop, 2000)
    const gestures = ['wheel', 'touchmove', 'keydown'] as const
    gestures.forEach((g) => window.addEventListener(g, stop, { passive: true }))

    return stop
  }, [route])
}
