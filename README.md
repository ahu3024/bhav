# MandiAlert — landing page

Vite + React + TypeScript. Hand-written CSS design system in [src/styles.css](src/styles.css) — no UI framework.

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # -> dist/
npm run preview  # serve the production build
```

## Design system

| Role | Value |
|---|---|
| Canvas | `#0F1310` (near-black, faint green cast) |
| Surface | `#151A15` (readout panels) |
| Ink | `#E8E6E1` / dim `#8B938A` |
| Hairline | `#262C25` |
| Accent | `#C6F135` (primary action, key figures, SELL signal) |
| Data-only | `#E0A43B` WAIT · `#E5544B` crash / miss — used **only** inside readouts |
| UI type | Inter Variable |
| Mono type | JetBrains Mono Variable — every figure, label, timestamp |
| Spacing | 4px scale (`--s-1` … `--s-32`) |
| Grid | 12 columns · 1200px · 24px gutter · asymmetric spans |

Constraints held: no background gradients or glow, no rounded cards with soft shadows
(0–1px radius, hairline borders, zero `box-shadow`), no three-column icon feature grid
(the method section is a numbered process ledger), no decorative badge pills.

## Content

All copy and mock numbers live in [src/data.ts](src/data.ts). Wire the real
values in once the backtest engine exists (see `../ROADMAP.md`).
