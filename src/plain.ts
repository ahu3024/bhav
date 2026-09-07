/**
 * Plain-language layer.
 *
 * Everything a farmer reads goes through here. The backend speaks in model
 * terms — NDVI, senescing, modal price, calibrated probability — and none of
 * that belongs on screen. One module so the same idea is never worded two ways
 * on two pages.
 */

import type { Alert } from './api'

/** The verdict, as a sentence rather than a colour code. */
export const VERDICT: Record<string, { word: string; line: string }> = {
  RED: {
    word: 'Sell now',
    line: 'Prices look likely to fall. Selling in the next few days should beat holding on.',
  },
  AMBER: {
    word: 'Be careful',
    line: 'It could go either way. Selling part of your crop now and holding the rest spreads the risk.',
  },
  GREEN: {
    word: 'Wait',
    line: 'Prices look likely to hold or rise. Waiting a little longer should pay more than selling today.',
  },
}

/** Crop stage from the satellite. */
export const CROP_STAGE: Record<string, string> = {
  Greening: 'Still growing',
  'At peak': 'Fully grown',
  Senescing: 'Drying down — harvest is near',
  'Harvest window': 'Ready to harvest',
}

/** Weather overlay ratings. */
export const HARVEST_WINDOW: Record<string, string> = {
  Good: 'Good — dry enough to lift the crop',
  Fair: 'Mixed — some days will work',
  Poor: 'Poor — too wet to lift the crop',
}

export const ROT_RISK: Record<string, string> = {
  Low: 'Low — stored crop should keep',
  Moderate: 'Some risk — check stored crop',
  High: 'High — stored crop may spoil',
}

export function stageWord(stage: string): string {
  return CROP_STAGE[stage] ?? stage
}

/** ₹ with Indian digit grouping and a real minus sign. */
export function rupees(n: number): string {
  const s = Math.round(Math.abs(n)).toLocaleString('en-IN')
  return `${n < 0 ? '−' : ''}₹${s}`
}

/** Per-quintal, spelled out — "qtl" is jargon on a phone screen. */
export function perQuintal(n: number): string {
  return `${rupees(n)} per quintal`
}

export function percent(fraction: number | null | undefined, digits = 0): string {
  if (fraction == null) return '—'
  return `${(fraction * 100).toFixed(digits)}%`
}

/**
 * What the call is worth, said as money in a pocket rather than a signed delta.
 * The sign means different things for different verdicts, so the wording has to
 * follow the verdict, not the number.
 *
 * `value` is kept separate from the surrounding words so the figure can be
 * animated (counted up) without the sentence around it having to be rebuilt.
 */
export function worthLine(
  alert: Alert,
): { prefix: string; value: number; suffix: string; caption: string } {
  const value = Math.round(Math.abs(alert.expected_impact_per_quintal))
  if (alert.color === 'GREEN') {
    return {
      prefix: 'about ',
      value,
      suffix: ' more per quintal',
      caption: 'what waiting could be worth, compared with selling today',
    }
  }
  if (alert.color === 'RED') {
    return {
      prefix: 'about ',
      value,
      suffix: ' per quintal',
      caption: 'what you could lose per quintal by holding on too long',
    }
  }
  return {
    prefix: 'around ',
    value,
    suffix: ' per quintal',
    caption: 'how much the price could move either way',
  }
}

/**
 * Confidence as a count of past weeks rather than a percentage — "83%" invites
 * false precision, "83 of the last 100 similar weeks" says where it came from.
 */
export function confidenceLine(alert: Alert): string {
  const pct = alert.calibrated_confidence ?? alert.confidence
  return `In the past, this pattern went the way we're calling it in about ${pct} out of 100 similar weeks.`
}

/** Which of the four inputs a model feature came from. */
export function factorSource(feature: string): 'satellite' | 'weather' | 'market' | 'history' {
  if (feature.startsWith('ndvi') || feature.startsWith('pct_area') || feature.startsWith('days_since'))
    return 'satellite'
  if (/^(rain|tmax|tmin|trange|humidity|dry_days|heat|wet_spell|vpd|harvest_score|rot)/.test(feature))
    return 'weather'
  if (/^(price|arr|mandi)/.test(feature)) return 'market'
  return 'history'
}

export const SOURCE_LABEL: Record<string, string> = {
  satellite: 'From the satellite',
  weather: 'From the weather',
  market: 'From the mandi',
  history: 'From past seasons',
}

/** Sentence-case a phrase the backend produced in lower case. */
export function sentence(text: string): string {
  if (!text) return text
  return text[0].toUpperCase() + text.slice(1)
}
