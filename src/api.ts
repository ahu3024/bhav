// Thin client for the Bhav backend (see ../backend). Set VITE_API_URL in
// .env.local to point somewhere other than a locally-running API.

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Factor = {
  feature: string
  effect: number
  direction: 'raises_sell_pressure' | 'supports_holding'
  phrase: string
  value: number
}

export type Score = {
  date: string
  drop_probability: number
  price_per_quintal: number
  horizon_days: number
  drop_threshold_pct: number
  factors: Factor[]
  model_kind: string
}

export type Alert = {
  district: string
  date: string
  color: 'RED' | 'AMBER' | 'GREEN'
  label: string
  window_start: string
  window_end: string
  expected_impact_per_quintal: number
  confidence: number
  reason: string
  score: Score
}

export type Backtest = {
  alert: Alert
  realized: {
    horizon_days: number
    price_now: number
    price_min: number | null
    price_max: number | null
    price_end: number | null
    max_drop_pct?: number
    actually_dropped?: boolean
  }
  outcome: {
    action: string
    baseline_label: string
    strategy_price_per_quintal: number
    baseline_price_per_quintal: number
    delta_per_quintal: number
    delta_pct: number
    call_was_right: boolean | null
  }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: { accept: 'application/json' } })
  if (!res.ok) throw new Error(`${path} -> ${res.status}`)
  return res.json() as Promise<T>
}

export const getAlertToday = () => get<Alert>('/alert/today')
export const getAlert = (date: string) => get<Alert>(`/alert?date=${date}`)
export const getBacktest = (date: string) => get<Backtest>(`/backtest?date=${date}`)

// Map a model feature name to the human source group shown on the card.
export function sourceOf(feature: string): string {
  if (feature.startsWith('ndvi')) return 'Sentinel-2'
  if (/^(rain|tmax|tmin|trange)/.test(feature)) return 'Weather'
  if (/^(price|arr)/.test(feature)) return 'Mandi'
  return 'Model'
}

export function formatDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  return d
    .toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
    .toUpperCase()
}
