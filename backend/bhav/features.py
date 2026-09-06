"""Feature store.

One function builds the full daily feature matrix by joining NDVI + weather +
mandi price on (district, date). Training uses the whole matrix; scoring asks for
a single as-of row. Same code path either way, so a backtest for any past date
uses exactly the features the model was trained on (roadmap "key design point").
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import DISTRICT, DROP_THRESHOLD_PCT, HORIZON_DAYS
from .db import read_df

FEATURE_COLS = [
    "ndvi", "ndvi_d7", "ndvi_d14", "ndvi_d30", "ndvi_vs_season",
    "rain_7", "rain_30", "rain_anom_30",
    "tmax_anom_14", "trange_14",
    "price", "price_mom_7", "price_mom_14", "price_mom_30",
    "price_vs_year", "price_pctile_year",
    "arr_7", "arr_mom_14", "arr_vs_year",
    "doy_sin", "doy_cos",
]


def _price_series() -> pd.DataFrame:
    """District-level daily modal price + arrivals (mean across Nashik markets)."""
    df = read_df(
        "SELECT date, price_per_quintal, arrivals_tonnes FROM mandi_price "
        "WHERE district = ?", (DISTRICT,)
    )
    if df.empty:
        raise RuntimeError("mandi_price is empty — run the ingest first")
    df["date"] = pd.to_datetime(df["date"])
    daily = (
        df.groupby("date")
        .agg(price=("price_per_quintal", "mean"),
             arrivals=("arrivals_tonnes", "sum"))
        .asfreq("D")
    )
    daily["price"] = daily["price"].interpolate("time").ffill().bfill()
    daily["arrivals"] = daily["arrivals"].fillna(0.0)
    return daily


def _ndvi_series(index: pd.DatetimeIndex | None = None) -> pd.Series:
    df = read_df("SELECT date, value FROM ndvi WHERE district = ?", (DISTRICT,))
    if df.empty:
        # GEE not provisioned yet (--skip-ndvi). Fall back to a flat neutral
        # series so NDVI features exist but carry ~no signal; swap in real data
        # later without touching the model code.
        import warnings

        warnings.warn("ndvi table empty — using a neutral placeholder series")
        if index is None:
            raise RuntimeError("ndvi is empty and no index to synthesise on")
        return pd.Series(0.45, index=index, name="ndvi")
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["value"].asfreq("D").interpolate("time")
    return s.ffill().bfill().rename("ndvi")


def _weather_frame() -> pd.DataFrame:
    df = read_df(
        "SELECT date, rainfall, temp_max, temp_min FROM weather WHERE district = ?",
        (DISTRICT,),
    )
    if df.empty:
        raise RuntimeError("weather is empty — run the ingest first")
    df["date"] = pd.to_datetime(df["date"])
    w = df.set_index("date").asfreq("D")
    for c in ("rainfall", "temp_max", "temp_min"):
        w[c] = w[c].interpolate("time").ffill().bfill()
    return w


def _seasonal_norm(s: pd.Series) -> pd.Series:
    """Day-of-year climatology, smoothed, broadcast back onto the index."""
    doy = s.index.dayofyear.where(~((s.index.month == 2) & (s.index.day == 29)), 59)
    clim = s.groupby(doy).mean()
    clim = pd.concat([clim, clim, clim]).rolling(15, center=True, min_periods=1)\
        .mean().iloc[len(clim):2 * len(clim)]
    clim.index = range(1, len(clim) + 1)
    return pd.Series(clim.reindex(doy).values, index=s.index)


def build_features(with_target: bool = True) -> pd.DataFrame:
    price = _price_series()
    weather = _weather_frame()
    ndvi = _ndvi_series(index=price.index.intersection(weather.index))

    idx = price.index.intersection(ndvi.index).intersection(weather.index)
    df = pd.DataFrame(index=idx).sort_index()
    p = price.loc[idx, "price"]
    arr = price.loc[idx, "arrivals"]
    nd = ndvi.loc[idx]
    w = weather.loc[idx]

    # --- NDVI ---
    df["ndvi"] = nd
    df["ndvi_d7"] = nd.diff(7)
    df["ndvi_d14"] = nd.diff(14)
    df["ndvi_d30"] = nd.diff(30)
    df["ndvi_vs_season"] = nd - _seasonal_norm(nd)

    # --- weather ---
    df["rain_7"] = w["rainfall"].rolling(7, min_periods=1).sum()
    df["rain_30"] = w["rainfall"].rolling(30, min_periods=1).sum()
    df["rain_anom_30"] = df["rain_30"] - _seasonal_norm(df["rain_30"])
    df["tmax_anom_14"] = (
        w["temp_max"].rolling(14, min_periods=1).mean()
        - _seasonal_norm(w["temp_max"]).rolling(14, min_periods=1).mean()
    )
    df["trange_14"] = (w["temp_max"] - w["temp_min"]).rolling(14, min_periods=1).mean()

    # --- price ---
    df["price"] = p
    df["price_mom_7"] = p.pct_change(7)
    df["price_mom_14"] = p.pct_change(14)
    df["price_mom_30"] = p.pct_change(30)
    year_med = p.rolling(365, min_periods=30).median()
    df["price_vs_year"] = p / year_med - 1.0
    df["price_pctile_year"] = p.rolling(365, min_periods=30).apply(
        lambda a: (a < a[-1]).mean(), raw=True
    )

    # --- arrivals ---
    df["arr_7"] = arr.rolling(7, min_periods=1).mean()
    df["arr_mom_14"] = arr.rolling(7, min_periods=1).mean().pct_change(14)
    arr_year_med = arr.rolling(365, min_periods=30).median().replace(0, np.nan)
    df["arr_vs_year"] = df["arr_7"] / arr_year_med - 1.0

    # --- calendar ---
    doy = df.index.dayofyear
    df["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)

    df = df.replace([np.inf, -np.inf], np.nan)

    if with_target:
        fwd_min = p.shift(-1).rolling(HORIZON_DAYS, min_periods=3).min().shift(
            -(HORIZON_DAYS - 1)
        )
        df["fwd_drop_pct"] = fwd_min / p - 1.0
        df["target"] = (df["fwd_drop_pct"] <= -DROP_THRESHOLD_PCT).astype("Int64")
        df.loc[fwd_min.isna(), "target"] = pd.NA

    return df


def training_frame() -> pd.DataFrame:
    df = build_features(with_target=True)
    df = df.dropna(subset=FEATURE_COLS + ["target"])
    df["target"] = df["target"].astype(int)
    return df


def feature_row_asof(date) -> pd.Series:
    """The feature vector as it would have looked on `date` (no lookahead)."""
    date = pd.Timestamp(date).normalize()
    df = build_features(with_target=False)
    df = df.loc[:date]
    if df.empty:
        raise ValueError(f"no feature data on or before {date.date()}")
    return df.iloc[-1]
