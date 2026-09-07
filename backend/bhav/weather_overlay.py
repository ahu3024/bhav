"""Weather overlay (roadmap §H2–H12: "weather anomalies", step 02 "local
temperature, rainfall and humidity are layered on — these shift harvest timing
and quality").

Raw daily weather is not decision-grade on its own; 12 mm of rain means one
thing in July and another in April. This module turns the daily archive into the
two questions a farmer actually faces:

    Can I lift and cure the crop?   -> harvest window
    Can I hold it if I don't sell?  -> rot risk

Both are windowed, causal and anomaly-based, so "wet" always means wet *for the
time of year* rather than wet in absolute mm. Every rolling window here looks
strictly backwards — same rule as phenology.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# A day with less than this much rain is workable for lifting/curing.
DRY_DAY_MM = 1.0
# Onion cures poorly and rots above roughly this humidity when it is also warm.
ROT_HUMIDITY = 70.0
ROT_TEMP_C = 20.0
# Nashik onion runs into heat stress past this; it pulls maturity forward.
HEAT_DAY_C = 35.0

WINDOW = 14  # the working horizon for "can I harvest this fortnight"

FEATURE_COLS = [
    "humidity_14",
    "humidity_anom_14",
    "dry_days_14",
    "wet_spell",
    "heat_days_14",
    "et0_anom_14",
]


def _wet_spell(rain: pd.Series) -> pd.Series:
    """Length of the run of consecutive wet days ending on each day.

    Three wet days in a row stops harvest outright; the same rainfall spread
    over a fortnight barely registers. Totals miss that, runs don't.
    """
    wet = (rain >= DRY_DAY_MM).astype(int)
    # Standard trick: cumulative count minus the cumulative count at the last
    # dry day resets the run to zero whenever it rains less than the threshold.
    group = (wet == 0).cumsum()
    return wet.groupby(group).cumsum().astype(float)


def add_overlay(weather: pd.DataFrame, seasonal_norm) -> pd.DataFrame:
    """Daily weather frame -> the overlay feature block.

    `seasonal_norm` is the causal day-of-year climatology from features.py,
    passed in so the anomalies here use exactly the same prior-years-only
    normal as the rest of the matrix.
    """
    w = weather
    out = pd.DataFrame(index=w.index)

    rain = w["rainfall"]
    hum = _col(w, "humidity_mean", default=55.0)
    tmax = w["temp_max"]
    tmean = _col(w, "temp_mean", default=(w["temp_max"] + w["temp_min"]) / 2)
    et0 = _col(w, "et0", default=np.nan)

    # --- can it be stored? ---
    out["humidity_14"] = hum.rolling(WINDOW, min_periods=1).mean()
    out["humidity_anom_14"] = out["humidity_14"] - seasonal_norm(out["humidity_14"])

    # --- can it be lifted and cured? ---
    out["dry_days_14"] = (
        (rain < DRY_DAY_MM).astype(float).rolling(WINDOW, min_periods=1).sum()
    )
    out["wet_spell"] = _wet_spell(rain)

    # --- does the heat pull the harvest forward? ---
    out["heat_days_14"] = (
        (tmax >= HEAT_DAY_C).astype(float).rolling(WINDOW, min_periods=1).sum()
    )

    # --- drying power, vs. what this time of year normally offers ---
    if et0.notna().any():
        et0_14 = et0.rolling(WINDOW, min_periods=1).mean()
        out["et0_anom_14"] = et0_14 - seasonal_norm(et0_14)
    else:
        out["et0_anom_14"] = np.nan

    # Composite scores, 0..1. Not model features — these are for the UI and the
    # alert reason, where "harvest window: poor" beats six numbers.
    out["harvest_score"] = _harvest_score(out["dry_days_14"], out["wet_spell"])
    out["rot_score"] = _rot_score(out["humidity_14"], tmean.rolling(
        WINDOW, min_periods=1).mean())
    return out


def _col(df: pd.DataFrame, name: str, default):
    """Column if the ingest provided it, else a fallback so older databases and
    the synthetic seed still build."""
    if name in df.columns and df[name].notna().any():
        return df[name]
    return pd.Series(default, index=df.index) if np.isscalar(default) else default


def _harvest_score(dry_days: pd.Series, wet_spell: pd.Series) -> pd.Series:
    """1 = a clear fortnight to lift and cure, 0 = washed out."""
    dry = (dry_days / WINDOW).clip(0, 1)
    # An active wet run is disqualifying regardless of the fortnight's total.
    penalty = (wet_spell / 3.0).clip(0, 1)
    return (dry * (1 - 0.7 * penalty)).clip(0, 1)


def _rot_score(humidity: pd.Series, temp: pd.Series) -> pd.Series:
    """1 = storage is a losing bet, 0 = the crop keeps.

    Humidity is the driver and warmth only accelerates it — weighting the two
    equally would understate the monsoon, which in Nashik is both the wettest
    and the *coolest* part of the year. So temperature scales the humidity
    term rather than gating it.
    """
    h = ((humidity - ROT_HUMIDITY) / 20.0).clip(0, 1)
    t = ((temp - ROT_TEMP_C) / 10.0).clip(0, 1)
    return (h * (0.55 + 0.45 * t)).clip(0, 1)


def _band(v: float | None, good: float, bad: float, labels: tuple[str, str, str]) -> str:
    if v is None or pd.isna(v):
        return "—"
    if v >= good:
        return labels[0]
    if v >= bad:
        return labels[1]
    return labels[2]


def describe(row: pd.Series) -> dict:
    """Human-facing weather panel for one date."""
    harvest = _get(row, "harvest_score")
    rot = _get(row, "rot_score")
    return {
        "harvest_window": _band(harvest, 0.66, 0.33, ("Good", "Fair", "Poor")),
        "harvest_score": _r(harvest),
        "rot_risk": _band(rot, 0.5, 0.2, ("High", "Moderate", "Low")),
        "rot_score": _r(rot),
        "humidity_mean_14": _r(_get(row, "humidity_14"), 1),
        "humidity_anom_14": _r(_get(row, "humidity_anom_14"), 1),
        "dry_days_14": _int(_get(row, "dry_days_14")),
        "wet_spell_days": _int(_get(row, "wet_spell")),
        "heat_days_14": _int(_get(row, "heat_days_14")),
        "rain_7_mm": _r(_get(row, "rain_7"), 1),
        "rain_anom_30_mm": _r(_get(row, "rain_anom_30"), 1),
        "note": _note(row),
        "window_days": WINDOW,
    }


def _note(row: pd.Series) -> str:
    """One line a person can act on, in the order that actually matters."""
    spell = _get(row, "wet_spell") or 0
    rot = _get(row, "rot_score") or 0
    harvest = _get(row, "harvest_score") or 0
    heat = _get(row, "heat_days_14") or 0
    rain_anom = _get(row, "rain_anom_30") or 0

    # A run this long is the monsoon itself, not a passing spell. Reporting it
    # as "97 straight wet days — lifting has stopped" is technically true, reads
    # as a broken number, and overstates a season everyone expects to be wet.
    if spell >= 21:
        return ("Monsoon rain is still running — the fields will not be dry "
                "enough to lift until it breaks.")
    if spell >= 3:
        return (f"{int(spell)} wet days in a row — lifting has stopped for now; "
                "expect arrivals to stall, then bunch up.")
    if rot >= 0.5:
        return ("Warm and humid — stored onion will not keep, so holding is "
                "riskier than the price alone suggests.")
    if harvest >= 0.66 and heat >= 7:
        return ("Dry and hot — good curing weather, and the heat is pulling "
                "maturity forward.")
    if harvest >= 0.66:
        return "Dry fortnight — a clean window to lift and cure."
    if rain_anom > 20:
        return "Wetter than normal for the season — harvest timing is slipping."
    return "Nothing unusual in the weather this fortnight."


def _get(row: pd.Series, key: str):
    v = row.get(key)
    return None if v is None or pd.isna(v) else float(v)


def _r(v, nd: int = 3):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def _int(v):
    return None if v is None or pd.isna(v) else int(round(float(v)))
