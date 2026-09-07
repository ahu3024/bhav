// Landing-page content. Numbers are illustrative — real values
// come from the backtest engine (see ../ROADMAP.md).

// `#/...` entries are pages (see router.ts); bare `#...` are in-page anchors and
// work from either page — the hash router treats anything without a leading
// slash as the landing route.
export const nav = [
  { label: "Today's call", href: '#/today' },
  { label: 'Check a past date', href: '#/backtest' },
  { label: 'How it works', href: '#how' },
  { label: 'Why trust it', href: '#trust' },
  { label: 'What it cannot do', href: '#limits' },
]

export const signal = {
  ref: 'EXAMPLE',
  date: '06 SEP 2026',
  market: 'NASHIK · ONION',
  action: 'WAIT',
  price: '+₹280 / quintal',
  factors: [
    { text: 'Crop is still filling out', src: 'Satellite' },
    { text: 'Dry enough to lift and cure', src: 'Weather' },
    { text: 'Little onion arriving yet', src: 'Mandi' },
  ],
  confidence: 78,
  foot: 'An example — hover for today’s real call →',
}

export const sources = [
  { label: 'Satellite', desc: 'Pictures of your fields from space, every few days' },
  { label: 'Weather', desc: 'Rain, heat and damp on your own block' },
  { label: 'Mandi', desc: 'What onion is actually fetching, and how much is arriving' },
  { label: 'Past seasons', desc: 'Nine years of what happened after weeks like this one' },
]

export const steps = [
  {
    n: '01',
    label: 'WE LOOK AT YOUR CROP FROM SPACE',
    desc: 'A satellite passes over Nashik every few days and photographs the fields. From how green they are, we can tell how far along the crop is — still growing, fully grown, or drying down ready to harvest.',
  },
  {
    n: '02',
    label: 'WE CHECK THE WEATHER ON THE GROUND',
    desc: 'Rain, heat and damp decide two things: whether you can get the crop out of the ground this fortnight, and whether it will keep once it is stored.',
  },
  {
    n: '03',
    label: 'WE WATCH THE MANDI',
    desc: 'Every day we take the rate and how much onion is arriving at your nearest mandis. Plenty of buyers and little arriving usually means the rate holds up.',
  },
  {
    n: '04',
    label: 'WE COMPARE IT WITH PAST SEASONS',
    desc: 'Then we look for weeks since 2016 that looked like this one — same crop stage, same weather, same market — and see what the rate actually did in the days that followed. That is where the answer comes from.',
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
    h: 'We can be wrong.',
    p: 'This is a pattern, not a promise. Even when we are fairly sure, some weeks still go the other way — and we show you those on the past-dates page rather than hiding them.',
  },
  {
    h: 'We are not a live rate ticker.',
    p: 'Bhav gives one call a week. If you need the rate right now, your mandi board is faster and more exact.',
  },
  {
    h: 'You know things we do not.',
    p: 'If you know something about your field, your buyer or your mandi that we cannot see from a satellite — trust that first. This is a second opinion, not an instruction.',
  },
]
