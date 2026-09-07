"""Crop phenology derived from the NDVI series (roadmap §H2–H12).

Turns a daily NDVI series into the four shape features the roadmap asks for —
greening rate, days since NDVI peak, senescence slope, % area past maturity —
plus the observation age that says how stale the satellite read is.

**Everything here is causal.** A textbook Savitzky-Golay filter is centred: the
smoothed value at day *t* is fitted through days on both sides of *t*, so it
knows the future. Used as-is that would leak straight into the backtest and
make every historical call look prescient. Instead we take the Savitzky-Golay
coefficients evaluated at the *trailing edge* of the window (`pos = w - 1`),
which fits the polynomial to the last `w` days only and reports its value — and
its derivative — at today. Same noise rejection, no lookahead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import savgol_coeffs

from .config import NDVI_MATURITY_THRESHOLD, NDVI_STALE_DAYS

# Savitzky-Golay windows, in days.
SMOOTH_WINDOW = 31       # ~3 composites — enough to ride out one cloudy pass
SMOOTH_POLY = 2          # quadratic: follows the green-up/senescence curve
SENESCENCE_WINDOW = 21   # the drying-down leg is short; keep it local
PEAK_LOOKBACK = 150      # ~one onion cycle, so "days since peak" stays in-season


def _causal_savgol(s: pd.Series, window: int, poly: int, deriv: int = 0) -> pd.Series:
    """Savitzky-Golay evaluated at the trailing edge of the window.

    `pos=window-1` asks scipy for the coefficients that estimate the fitted
    polynomial (or its `deriv`-th derivative) at the *last* sample, so the value
    at day t uses days t-window+1 .. t and nothing after.
    """
    if len(s) < window:
        return pd.Series(np.nan, index=s.index)
    coeffs = savgol_coeffs(window, poly, deriv=deriv, delta=1.0,
                           pos=window - 1, use="dot")
    return s.rolling(window).apply(lambda a: float(coeffs @ a), raw=True)


def _days_since_peak(smooth: pd.Series, lookback: int = PEAK_LOOKBACK) -> pd.Series:
    """Days since the highest smoothed NDVI within the trailing window.

    Reads as "how far past green-up is this crop" — the closer the peak recedes,
    the nearer the harvest, and the nearer the arrivals surge.
    """
    def since(a: np.ndarray) -> float:
        return float(len(a) - 1 - int(np.nanargmax(a)))

    return smooth.rolling(lookback, min_periods=20).apply(since, raw=True)


def add_phenology(
    ndvi: pd.Series,
    pct_mature: pd.Series | None = None,
    obs_age_days: pd.Series | None = None,
) -> pd.DataFrame:
    """Daily NDVI -> the phenology feature block, indexed like `ndvi`."""
    ndvi = ndvi.astype(float)
    out = pd.DataFrame(index=ndvi.index)

    out["ndvi_smooth"] = _causal_savgol(ndvi, SMOOTH_WINDOW, SMOOTH_POLY)
    # First derivative of the same fit: NDVI units per day. Positive = the belt
    # is still greening up, negative = it is drying down toward harvest.
    out["ndvi_greening_rate"] = _causal_savgol(
        ndvi, SMOOTH_WINDOW, SMOOTH_POLY, deriv=1)
    out["ndvi_days_since_peak"] = _days_since_peak(out["ndvi_smooth"])
    # Senescence is only interesting while the crop is actually declining, so
    # clip the short-window slope to its negative half and report it as a
    # positive "drying speed".
    short_slope = _causal_savgol(ndvi, SENESCENCE_WINDOW, 1, deriv=1)
    out["ndvi_senescence_slope"] = (-short_slope).clip(lower=0.0)

    if pct_mature is not None:
        out["ndvi_pct_mature"] = pct_mature.reindex(ndvi.index).astype(float)
    else:
        # No per-pixel composite available (synthetic or legacy data): infer the
        # matured share from how far the belt mean sits below the cut.
        out["ndvi_pct_mature"] = (
            (NDVI_MATURITY_THRESHOLD - ndvi) / NDVI_MATURITY_THRESHOLD + 0.5
        ).clip(0.0, 1.0)

    out["ndvi_obs_age_days"] = (
        obs_age_days.reindex(ndvi.index).astype(float)
        if obs_age_days is not None
        else 0.0
    )
    return out


def stage_of(row: pd.Series) -> str:
    """One-word crop stage for the UI, from the phenology block."""
    rate = row.get("ndvi_greening_rate", 0.0) or 0.0
    mature = row.get("ndvi_pct_mature", 0.0) or 0.0
    if mature >= 0.65:
        return "Harvest window"
    if rate > 0.0015:
        return "Greening"
    if rate < -0.0015:
        return "Senescing"
    return "At peak"


def describe(row: pd.Series) -> dict:
    """Human-facing NDVI panel for one date — what the satellite currently says."""
    age = row.get("ndvi_obs_age_days")
    age = None if age is None or pd.isna(age) else int(age)
    return {
        "ndvi": _f(row.get("ndvi")),
        "ndvi_smooth": _f(row.get("ndvi_smooth")),
        "greening_rate_per_day": _f(row.get("ndvi_greening_rate"), 5),
        "days_since_peak": None if pd.isna(row.get("ndvi_days_since_peak"))
        else int(row["ndvi_days_since_peak"]),
        "senescence_slope": _f(row.get("ndvi_senescence_slope"), 5),
        "pct_area_past_maturity": _f(row.get("ndvi_pct_mature")),
        "obs_age_days": age,
        "stale": age is not None and age > NDVI_STALE_DAYS,
        "stage": stage_of(row),
        "maturity_threshold": NDVI_MATURITY_THRESHOLD,
    }


def _f(v, nd: int = 4):
    return None if v is None or pd.isna(v) else round(float(v), nd)
