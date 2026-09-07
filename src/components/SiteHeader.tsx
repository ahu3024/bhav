import { nav } from '../data'

export default function SiteHeader() {
  return (
    <header className="site-header">
      <div className="container site-header__inner">
        <a className="brand" href="#/">
          Bhav.
        </a>
        <nav className="nav-links">
          {nav.map((item) => (
            <a key={item.label} href={item.href}>
              {item.label}
            </a>
          ))}
        </nav>
        <a className="btn btn--wa" href="#get-alerts">
          Get alerts on WhatsApp
        </a>
      </div>
    </header>
  )
}
