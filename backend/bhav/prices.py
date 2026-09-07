"""Mandi price cleaning (roadmap §H2–H12: "clean prices: holidays/zero-arrival
days, outlier caps, CPI deflation, log").

Agmarknet reports one row per market per variety per trading day. Turning that
into the single district series the model reads takes four decisions, and each
one is somewhere a backtest can quietly go wrong:

1. **Aggregation.** Arrivals-weighted, not a plain mean. Lasalgaon clearing
   2,000 tonnes and a private yard clearing 3 tonnes are not two equal opinions
   about the price of onion.
2. **Non-trading days.** Mandis close for Sundays, holidays and bandhs — 624 of
   the 3,901 days in this window have no print at all. Short gaps are
   interpolated; longer ones are held forward and the staleness is carried as
   `days_since_trade`, the same treatment NDVI's observation age gets.
3. **Outliers.** A single fat-fingered print can move a district mean hard.
   Capped against a *trailing* robust band, never a centred one.
4. **Deflation.** Every level and long-horizon comparison runs on CPI-deflated
   price; nominal rupees are kept only for what a farmer is shown.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (
    CROP,
    DISTRICT,
    PRICE_MAX_GAP_DAYS,
    PRICE_OUTLIER_MAD,
    PRICE_OUTLIER_WINDOW,
)
from .db import read_df

# CPI year used as the base for deflation — real prices are expressed in the
# rupees of this year, so the ₹ figures stay recognisable.
_BASE_YEAR_OFFSET = 0  # 0 = latest year in the CPI table


def _cpi_deflator(index: pd.DatetimeIndex) -> pd.Series:
    """Daily deflator: divide a nominal price by this to get real rupees."""
    cpi = read_df("SELECT year, cpi FROM cpi ORDER BY year")
    if cpi.empty:
        # No CPI loaded — deflation becomes a no-op rather than a crash, so the
        # pipeline still runs on a fresh clone.
        return pd.Series(1.0, index=index)

    base = float(cpi["cpi"].iloc[-1 - _BASE_YEAR_OFFSET])
    by_year = dict(zip(cpi["year"].astype(int), cpi["cpi"].astype(float)))
    first, last = min(by_year), max(by_year)
    years = pd.Series(index.year, index=index).clip(first, last)
    return years.map(by_year).astype(float) / base


def _cap_outliers(price: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Clip prints far from a trailing robust band. Returns (capped, was_capped).

    The window is trailing and shifted by one day on purpose: a centred window,
    or one that includes today, lets the outlier defend itself by widening the
    very band meant to catch it — and worse, leaks future prices into a
    point-in-time feature.
    """
    med = price.rolling(PRICE_OUTLIER_WINDOW, min_periods=5).median().shift(1)
    mad = (price - med).abs().rolling(
        PRICE_OUTLIER_WINDOW, min_periods=5).median().shift(1)
    # 1.4826 scales MAD to a standard-deviation equivalent for normal data.
    band = PRICE_OUTLIER_MAD * 1.4826 * mad
    lo, hi = med - band, med + band
    capped = price.clip(lower=lo, upper=hi)
    # Where there's no band yet (warm-up) keep the original print.
    capped = capped.where(med.notna() & mad.notna() & (mad > 0), price)
    return capped, capped.ne(price)


def district_daily() -> pd.DataFrame:
    """The cleaned district-level daily price series the feature store reads.

    Columns: price (nominal modal ₹/qtl), price_real (CPI-deflated),
    log_price, price_min/price_max, arrivals, n_markets, traded,
    days_since_trade, price_capped.
    """
    raw = read_df(
        "SELECT date, market, variety, arrivals_tonnes, price_min, "
        "price_modal, price_max FROM mandi_price WHERE district = ? AND crop = ?",
        (DISTRICT, CROP),
    )
    if raw.empty:
        raise RuntimeError("mandi_price is empty — run the ingest first")

    raw["date"] = pd.to_datetime(raw["date"])
    for c in ("arrivals_tonnes", "price_min", "price_modal", "price_max"):
        raw[c] = pd.to_numeric(raw[c], errors="coerce")

    # --- sanity filter: drop prints that cannot be true -----------------------
    ok = raw["price_modal"] > 0
    ok &= raw["price_min"].isna() | (raw["price_modal"] >= raw["price_min"])
    ok &= raw["price_max"].isna() | (raw["price_modal"] <= raw["price_max"])
    ok &= raw["arrivals_tonnes"].isna() | (raw["arrivals_tonnes"] >= 0)
    raw = raw[ok]

    # --- aggregate to one row per trading day, weighted by arrivals ----------
    w = raw["arrivals_tonnes"].fillna(0.0)
    # A day where every market reports zero arrivals still has a price; fall
    # back to an equal weighting rather than dividing by zero.
    raw = raw.assign(_w=np.where(w > 0, w, 1e-9))
    grouped = raw.groupby("date")

    daily = pd.DataFrame({
        "price": grouped.apply(
            lambda g: np.average(g["price_modal"], weights=g["_w"]),
            include_groups=False),
        "price_min": grouped["price_min"].min(),
        "price_max": grouped["price_max"].max(),
        "arrivals": grouped["arrivals_tonnes"].sum(),
        "n_markets": grouped["market"].nunique(),
    })

    # --- put it on a continuous daily grid ----------------------------------
    full = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    out = daily.reindex(full)
    out["traded"] = out["price"].notna()

    # Days since the last actual print — a closed mandi is not a flat market,
    # and the model should be able to tell the difference.
    last_trade = pd.Series(
        np.where(out["traded"], out.index, np.datetime64("NaT")), index=out.index
    ).ffill()
    out["days_since_trade"] = (
        out.index - pd.to_datetime(last_trade)).dt.days.astype(float)
    out["days_since_trade"] = out["days_since_trade"].fillna(0.0)

    # Short closures interpolate; a long shutdown holds the last print instead
    # of inventing a trend across it.
    out["price"] = out["price"].interpolate(
        "time", limit=PRICE_MAX_GAP_DAYS, limit_area="inside").ffill()
    for c in ("price_min", "price_max"):
        out[c] = out[c].interpolate(
            "time", limit=PRICE_MAX_GAP_DAYS, limit_area="inside").ffill()
    out["arrivals"] = out["arrivals"].fillna(0.0)      # closed mandi = no arrivals
    out["n_markets"] = out["n_markets"].fillna(0).astype(int)

    # --- outlier caps + deflation + log -------------------------------------
    out["price"], out["price_capped"] = _cap_outliers(out["price"])
    deflator = _cpi_deflator(out.index)
    out["price_real"] = out["price"] / deflator
    out["log_price"] = np.log(out["price_real"])
    return out


def summary() -> dict:
    """Quick provenance/quality read-out for the API and the README."""
    d = district_daily()
    return {
        "start": d.index.min().strftime("%Y-%m-%d"),
        "end": d.index.max().strftime("%Y-%m-%d"),
        "days": int(len(d)),
        "trading_days": int(d["traded"].sum()),
        "non_trading_days": int((~d["traded"]).sum()),
        "outliers_capped": int(d["price_capped"].sum()),
        "markets_max": int(d["n_markets"].max()),
        "price_now": round(float(d["price"].iloc[-1]), 2),
        "longest_closure_days": int(d["days_since_trade"].max()),
    }
