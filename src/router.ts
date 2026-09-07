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

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash))

  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return route
}

/** Scroll to the top on a route change, but leave in-page anchors alone. */
export function useScrollReset(route: Route) {
  useEffect(() => {
    if (!window.location.hash.includes('#', 1)) window.scrollTo(0, 0)
  }, [route])
}
