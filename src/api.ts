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
  calibrated_probability?: number
  is_calibrated?: boolean
}

export type Alert = {
  district: string
  date: string
  color: 'RED' | 'AMBER' | 'GREEN'
  label: string
  window_start: string
  window_end: string
  expected_impact_per_quintal: number
  /** Raw: distance from a coin flip. Kept for reference; not what we display. */
  confidence: number
  /**
   * Isotonic-calibrated probability that this call is the right one, 0–100.
   * The raw score overstates itself at the top end, so this is the number the
   * dashboard shows. Optional so an older backend still renders.
   */
  calibrated_confidence?: number
  reason: string
  score: Score
}

/** Prefer the calibrated number; fall back to raw if the backend is older. */
export function displayConfidence(a: Alert): number {
  return a.calibrated_confidence ?? a.confidence
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

// --- satellite NDVI ---------------------------------------------------------

/** The satellite's read of the crop on one date. */
export type NdviRead = {
  ndvi: number | null
  ndvi_smooth: number | null
  greening_rate_per_day: number | null
  days_since_peak: number | null
  senescence_slope: number | null
  pct_area_past_maturity: number | null
  obs_age_days: number | null
  stale: boolean
  stage: string
  maturity_threshold: number
}

/** One 10-day Sentinel-2 composite — a real observation. */
export type NdviComposite = {
  date: string
  ndvi: number | null
  pct_mature: number | null
  clear_frac: number | null
  n_obs: number | null
}

/** The daily grid the model reads: composites held forward, plus the age. */
export type NdviDay = {
  date: string
  ndvi: number | null
  smooth: number | null
  pct_mature: number | null
  obs_age_days: number | null
}

export type NdviSeries = {
  district: string
  crop: string
  start: string
  end: string
  maturity_threshold: number
  composite_days: number
  current: NdviRead
  composites: NdviComposite[]
  daily: NdviDay[]
}

// --- WhatsApp delivery ------------------------------------------------------

export type Lang = 'en' | 'hi' | 'mr'

export const LANG_NAMES: Record<Lang, string> = {
  en: 'English',
  hi: 'हिंदी',
  mr: 'मराठी',
}

export type MessagePreview = {
  alert: Alert
  texts: Record<Lang, string>
}

/**
 * Delivery runs on open-wa, which drives a real WhatsApp account through
 * WhatsApp Web — so there is no 24-hour window and no approved template to
 * wait on. What can go wrong instead is the session: the bridge has to be
 * running, and a phone has to have scanned the pairing QR.
 */
export type DeliveryStatus = {
  provider: string
  /** Is the bridge process reachable at all. */
  configured: boolean
  bridge_url: string
  /** starting | qr | connected | failed | unreachable */
  session_status: string
  /** The phone number the session is linked to, once it is. */
  linked_number: string | null
  /** A pairing QR is waiting to be scanned at /message/qr. */
  qr_available: boolean
  /** The only field that means "a message will actually go out". */
  whatsapp_ready: boolean
  sent?: number
  failed?: number
  reason?: string | null
  credentials?: { ok: boolean; reason?: string; display_phone_number?: string }
}

export type SubscribeResult = {
  subscriber: { phone: string; lang: string; active: number }
  welcome: {
    sent: boolean
    channel?: string
    reason?: string
    /** The specific thing to go and do about `reason`, when we know it. */
    hint?: string
  } | null
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    // FastAPI puts the useful part in `detail`; surface it rather than a code.
    let detail = `${path} -> ${res.status}`
    try {
      const j = await res.json()
      if (j?.detail) detail = String(j.detail)
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const getMessagePreviews = () =>
  post<MessagePreview>('/message/preview/all', {})
export const getDeliveryStatus = () => get<DeliveryStatus>('/message/status')
/** The open-wa pairing QR. 409s once the session is linked. */
export const whatsappQrUrl = () => `${BASE}/message/qr`
export const subscribe = (body: {
  phone: string
  name?: string
  village_pin?: string
  lang: Lang
  sell_window?: string
}) => post<SubscribeResult>('/subscribe', body)

// --- weather overlay --------------------------------------------------------

/** The weather overlay's read of one date: can it be lifted, can it be held. */
export type WeatherRead = {
  harvest_window: string
  harvest_score: number | null
  rot_risk: string
  rot_score: number | null
  humidity_mean_14: number | null
  humidity_anom_14: number | null
  dry_days_14: number | null
  wet_spell_days: number | null
  heat_days_14: number | null
  rain_7_mm: number | null
  rain_anom_30_mm: number | null
  note: string
  window_days: number
}

export type WeatherDay = {
  date: string
  rain_mm: number | null
  humidity: number | null
  temp_max: number | null
  harvest_score: number | null
  rot_score: number | null
}

export type WeatherSeries = {
  district: string
  crop: string
  start: string
  end: string
  current: WeatherRead
  daily: WeatherDay[]
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: { accept: 'application/json' } })
  if (!res.ok) throw new Error(`${path} -> ${res.status}`)
  return res.json() as Promise<T>
}

export const getAlertToday = () => get<Alert>('/alert/today')
export const getAlert = (date: string) => get<Alert>(`/alert?date=${date}`)
export const getBacktest = (date: string) => get<Backtest>(`/backtest?date=${date}`)
export const getNdvi = (days = 400) => get<NdviSeries>(`/ndvi?days=${days}`)
export const getNdviAsOf = (date: string) => get<NdviRead>(`/ndvi/asof?date=${date}`)
export const getWeather = (days = 400) => get<WeatherSeries>(`/weather?days=${days}`)
export const getWeatherAsOf = (date: string) =>
  get<WeatherRead>(`/weather/asof?date=${date}`)

/** Turn a fetch failure into something a person can act on. */
export function friendlyError(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e)
  if (msg.includes('Failed to fetch'))
    return 'Backend not reachable — start it with `uvicorn bhav.api:app` on :8000.'
  if (msg.includes('503'))
    return 'Backend is up but has no data yet — run `python -m scripts.seed_demo` then `python -m scripts.build`.'
  return msg
}

// Map a model feature name to the human source group shown on the card.
export function sourceOf(feature: string): string {
  if (feature.startsWith('ndvi')) return 'Sentinel-2'
  if (/^(rain|tmax|tmin|trange)/.test(feature)) return 'Weather'
  if (/^(price|arr)/.test(feature)) return 'Mandi'
  return 'Model'
}

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

export function formatDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${String(d).padStart(2, '0')} ${MONTHS[m - 1]} ${y}`
}
