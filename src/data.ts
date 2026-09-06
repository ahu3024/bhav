// Landing-page content. Numbers are illustrative — real values
// come from the backtest engine (see ../ROADMAP.md).

export const nav = [
  { label: 'How it works', href: '#how' },
  { label: 'Backtest', href: '#backtest' },
  { label: 'Why trust it', href: '#trust' },
  { label: 'Limits', href: '#limits' },
]

export const signal = {
  ref: 'BHAV / SIGNAL 104',
  date: '06 SEP 2026',
  market: 'NASHIK · ONION',
  action: 'WAIT',
  price: '+₹280 / QTL',
  factors: [
    { text: '40% crop still maturing', src: 'Sentinel-2' },
    { text: '14 seasons matched', src: 'Historical' },
    { text: '4–6 days optimal window', src: 'Mandi flow' },
  ],
  confidence: 78,
  foot: 'View Raw NDVI →',
}

export const sources = [
  { label: 'Satellite', desc: 'Crop health monitoring via Sentinel-2' },
  { label: 'Weather', desc: 'Local humidity & rainfall triggers' },
  { label: 'Mandi', desc: 'APMC real-time price & volume flow' },
  { label: 'History', desc: '9-year pattern-matched validation' },
]

export const steps = [
  {
    n: '01',
    label: 'SATELLITE NDVI',
    desc: 'We pull 10m-resolution crop imagery for your district. NDVI tells us growth stage, stress, and how much crop is still maturing.',
  },
  {
    n: '02',
    label: 'WEATHER OVERLAY',
    desc: 'Local temperature, rainfall, and humidity are layered on. These shift harvest timing and quality.',
  },
  {
    n: '03',
    label: 'MANDI ARRIVALS + PRICE',
    desc: 'Daily price and volume data from your nearest APMC mandi. Thin arrivals + healthy crop = likely price rise.',
  },
  {
    n: '04',
    label: 'PATTERN MATCH',
    desc: "We compare this week's signal fingerprint against 9 years of weekly data. If 14 out of 18 similar weeks saw prices rise within 4–6 days, that's the basis for WAIT.",
  },
]

export type FpRow = { k: string; v: string; mono?: boolean; hot?: boolean }

export const fingerprint: { id: string; rows: FpRow[] } = {
  id: 'FINGERPRINT: NASHIK_ONION_S104',
  rows: [
    { k: 'Pattern ID', v: '104', mono: true },
    { k: 'Region', v: 'Nashik' },
    { k: 'Commodity', v: 'Onion' },
    { k: 'Window', v: 'Sep W1', mono: true },
    { k: 'Matches', v: '14/18 weeks', mono: true },
    { k: 'Favorable', v: '11/14 (78%)', hot: true },
  ],
}

export const limits = [
  {
    h: 'No guarantee of profit.',
    p: 'Patterns describe probability, not certainty. A 78% confidence still means 22% of similar weeks went the other way.',
  },
  {
    h: 'No real-time trading.',
    p: 'Bhav generates a signal once per week. It is not a live trading tool or price ticker.',
  },
  {
    h: 'No replacement for local knowledge.',
    p: "If you know something about your field, your buyer, or your mandi that data doesn't capture — trust that first.",
  },
]
