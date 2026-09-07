import { nav } from '../data'
import type { Route } from '../router'

export default function SiteHeader({ route }: { route: Route }) {
  return (
    <header className="site-header">
      <div className="container site-header__inner">
        <a className="brand" href="#/">
          Bhav.
        </a>
        <nav className="nav-links">
          {nav.map((item) => {
            const isPage = item.href.startsWith('#/')
            const active = isPage
              ? item.href === `#${route}`
              : route === '/' && false
            return (
              <a
                key={item.label}
                href={item.href}
                className={active ? 'is-active' : undefined}
                aria-current={active ? 'page' : undefined}
              >
                {item.label}
              </a>
            )
          })}
        </nav>
        <a className="btn btn--wa" href="#get-alerts">
          Get alerts on WhatsApp
        </a>
      </div>
    </header>
  )
}
