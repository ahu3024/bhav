"""Feature store.

One function builds the full daily feature matrix by joining NDVI + weather +
mandi price on (district, date). Training uses the whole matrix; scoring asks for
a single as-of row. Same code path either way, so a backtest for any past date
uses exactly the features the model was trained on (roadmap "key design point").
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (
    DISTRICT,
    DROP_THRESHOLD_PCT,
    HORIZON_DAYS,
    NDVI_COMPOSITE_DAYS,
)
from .db import data_version, read_df
from .phenology import add_phenology
from .prices import district_daily
from .weather_overlay import FEATURE_COLS as WEATHER_OVERLAY_COLS, add_overlay

FEATURE_COLS = [
    "ndvi", "ndvi_d7", "ndvi_d14", "ndvi_d30", "ndvi_vs_season",
    # Phenology block — the shape of the crop cycle, not just its level.
    "ndvi_greening_rate", "ndvi_days_since_peak", "ndvi_senescence_slope",
    "ndvi_pct_mature", "ndvi_obs_age_days",
    "rain_7", "rain_30", "rain_anom_30",
    "tmax_anom_14", "trange_14",
    # Weather overlay — harvest workability and storage risk, not raw mm.
    *WEATHER_OVERLAY_COLS,
    # Deflated price, not nominal — see the price block in build_features.
    "price_real", "price_mom_7", "price_mom_14", "price_mom_30",
    "price_vs_year", "price_pctile_year", "days_since_trade",
    "arr_7", "arr_mom_14", "arr_vs_year",
    "doy_sin", "doy_cos",
]


def _price_series() -> pd.DataFrame:
    """Cleaned district-level daily price + arrivals.

    All of the work — arrivals-weighted aggregation across markets, non-trading
    days, outlier caps, CPI deflation — lives in prices.py. See that module for
    why each decision is made the way it is.
    """
    return district_daily()


def _ndvi_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Daily NDVI aligned onto `index`, from the 10-day composite table.

    Sentinel-2 sees the belt every few days at best, and the monsoon can hide it
    for weeks. Rather than interpolate that gap away and pretend to a daily
    read, each composite is **held forward** until the next one lands and the
    staleness is carried explicitly as `ndvi_obs_age_days` — which is a model
    feature in its own right, so a decision made on a three-week-old picture is
    visibly weaker than one made on this morning's pass.
    """
    df = read_df(
        "SELECT date, value, pct_mature, clear_frac, obs_date FROM ndvi "
        "WHERE district = ?", (DISTRICT,)
    )
    if df.empty:
        # GEE not provisioned yet (--skip-ndvi). Flat neutral series so the NDVI
        # features exist but carry ~no signal; real data swaps in later without
        # touching the model code.
        import warnings

        warnings.warn("ndvi table empty — using a neutral placeholder series")
        return pd.DataFrame(
            {"ndvi": 0.45, "pct_mature": np.nan, "obs_age": np.nan}, index=index
        )

    df["date"] = pd.to_datetime(df["date"])
    # obs_date is the last real satellite pass in the composite; fall back to
    # the composite *end* for legacy rows that predate the column.
    period_end = df["date"] + pd.Timedelta(days=NDVI_COMPOSITE_DAYS - 1)
    df["obs_date"] = pd.to_datetime(
        df.get("obs_date", pd.Series(pd.NaT, index=df.index))
    ).fillna(period_end)

    # Key point-in-time rule: a composite becomes knowable only once its last
    # contributing pass has happened, so it is indexed by obs_date — not by the
    # window start. Indexing by the start would hand days early in the window a
    # value derived from passes up to nine days in their future, which is
    # exactly the leak that makes a backtest look prescient.
    df = (
        df.sort_values("obs_date")
        .drop_duplicates("obs_date", keep="last")
        .set_index("obs_date")
    )

    full = df.reindex(index.union(df.index)).sort_index()
    out = pd.DataFrame(index=full.index)
    out["ndvi"] = full["value"].ffill()
    out["pct_mature"] = full["pct_mature"].ffill()
    # Days since the last real observation, at every point on the daily grid.
    last_obs = pd.Series(full.index.where(full["value"].notna()), index=full.index)
    out["obs_age"] = (out.index - last_obs.ffill()).dt.days.astype("float")
    # Before the satellite record starts there is nothing to hold forward; back-
    # fill the level so early rows still join, and leave the age unbounded-old.
    out["ndvi"] = out["ndvi"].bfill()
    out["pct_mature"] = out["pct_mature"].bfill()
    out["obs_age"] = out["obs_age"].fillna(999.0)
    return out.reindex(index)


# Columns the overlay can use when the ingest provides them. Older databases
# (and the pre-humidity seed) only have the first three; weather_overlay.py
# falls back rather than failing.
_WEATHER_COLS = [
    "rainfall", "temp_max", "temp_min",
    "rain_hours", "temp_mean", "humidity_max", "humidity_min", "humidity_mean",
    "et0", "wind_max",
]


def _weather_frame() -> pd.DataFrame:
    have = set(read_df("SELECT * FROM weather LIMIT 1").columns)
    cols = [c for c in _WEATHER_COLS if c in have]
    if not {"rainfall", "temp_max", "temp_min"} <= set(cols):
        raise RuntimeError("weather table is missing its core columns")

    df = read_df(
        f"SELECT date, {', '.join(cols)} FROM weather WHERE district = ?",
        (DISTRICT,),
    )
    if df.empty:
        raise RuntimeError("weather is empty — run the ingest first")
    df["date"] = pd.to_datetime(df["date"])
    w = df.set_index("date").asfreq("D")
    for c in cols:
        # Rain is a total, not a level: a missing day is a dry day, and
        # interpolating it would invent a drizzle that stops a wet-spell run.
        w[c] = w[c].fillna(0.0) if c in ("rainfall", "rain_hours") \
            else w[c].interpolate("time").ffill().bfill()
    return w


# Width of the day-of-year bucket the climatology averages over. Wide enough to
# pool several passes per season, narrow enough to keep the seasonal shape.
_CLIM_BUCKET_DAYS = 15


def _seasonal_norm(s: pd.Series) -> pd.Series:
    """Day-of-year climatology using **only prior years**.

    "Is this rainfall high for the time of year?" needs a normal to compare
    against, and the obvious way to build one — average each day-of-year across
    the whole series — quietly tells 2019 what 2024 did. The anomaly features
    then look sharper in a backtest than they could ever be live.

    So the normal for a date is the expanding mean of its day-of-year bucket
    over everything strictly before it. Early rows have no prior season and come
    back NaN, which the warm-up drop already handles.
    """
    doy = s.index.dayofyear.where(~((s.index.month == 2) & (s.index.day == 29)), 59)
    bucket = pd.Series((doy - 1) // _CLIM_BUCKET_DAYS, index=s.index)
    return s.groupby(bucket).transform(
        lambda x: x.expanding().mean().shift(1)
    )


_CACHE: dict[tuple, pd.DataFrame] = {}


def _db_stamp() -> str:
    """Cache key that changes whenever an *ingest* rewrites a source table.

    Was the database file's mtime, which the API moved itself every time it
    persisted an alert row while serving /alert/today -- so the cache was cold
    on literally every request and each one paid a full rebuild. db.data_version
    is bumped only by write_df, so serving no longer invalidates serving.
    """
    return data_version()


def build_features(with_target: bool = True) -> pd.DataFrame:
    """Cached: the track-record walk scores hundreds of dates, and each one
    would otherwise rebuild this whole matrix from sqlite. Keyed on the data
    version so a re-ingest or a re-seed invalidates it without a restart."""
    key = (with_target, _db_stamp())
    hit = _CACHE.get(key)
    if hit is not None:
        return hit

    df = _build_features_uncached(with_target)
    _CACHE.clear()          # only ever hold the current db generation
    _CACHE[key] = df
    return df


def _build_features_uncached(with_target: bool = True) -> pd.DataFrame:
    price = _price_series()
    weather = _weather_frame()
    idx = price.index.intersection(weather.index)
    ndvi = _ndvi_frame(index=idx)

    df = pd.DataFrame(index=idx).sort_index()
    p = price.loc[idx, "price"]            # nominal ₹/qtl — for display + outcomes
    pr = price.loc[idx, "price_real"]      # CPI-deflated — what the model reads
    arr = price.loc[idx, "arrivals"]
    nd = ndvi["ndvi"]
    w = weather.loc[idx]

    # --- NDVI level + trend ---
    df["ndvi"] = nd
    df["ndvi_d7"] = nd.diff(7)
    df["ndvi_d14"] = nd.diff(14)
    df["ndvi_d30"] = nd.diff(30)
    df["ndvi_vs_season"] = nd - _seasonal_norm(nd)

    # --- NDVI phenology (causal Savitzky-Golay; see phenology.py) ---
    df = df.join(add_phenology(nd, ndvi["pct_mature"], ndvi["obs_age"]))

    # --- weather ---
    df["rain_7"] = w["rainfall"].rolling(7, min_periods=1).sum()
    df["rain_30"] = w["rainfall"].rolling(30, min_periods=1).sum()
    df["rain_anom_30"] = df["rain_30"] - _seasonal_norm(df["rain_30"])
    df["tmax_anom_14"] = (
        w["temp_max"].rolling(14, min_periods=1).mean()
        - _seasonal_norm(w["temp_max"]).rolling(14, min_periods=1).mean()
    )
    df["trange_14"] = (w["temp_max"] - w["temp_min"]).rolling(14, min_periods=1).mean()

    # --- weather overlay: harvest window + storage risk (weather_overlay.py) ---
    # rain_7 / rain_anom_30 are already on df and the overlay's note reads them,
    # so hand it the joined frame rather than the raw weather table.
    df = df.join(add_overlay(w.join(df[["rain_7", "rain_anom_30"]]), _seasonal_norm))

    # --- price ---
    # Two series on purpose. `price` stays nominal because that is what a farmer
    # is quoted and what the ₹/quintal outcome has to be measured in. Everything
    # the *model* sees runs on the CPI-deflated series: a decade of inflation
    # would otherwise read as a decade of slow bull market, and every "price is
    # high for the season" comparison against a rolling year would drift.
    df["price"] = p
    df["price_real"] = pr
    df["price_mom_7"] = pr.pct_change(7)
    df["price_mom_14"] = pr.pct_change(14)
    df["price_mom_30"] = pr.pct_change(30)
    year_med = pr.rolling(365, min_periods=30).median()
    df["price_vs_year"] = pr / year_med - 1.0
    df["price_pctile_year"] = pr.rolling(365, min_periods=30).apply(
        lambda a: (a < a[-1]).mean(), raw=True
    )
    # A closed mandi is not a flat market — carry the staleness explicitly, the
    # same way NDVI carries its observation age.
    df["days_since_trade"] = price.loc[idx, "days_since_trade"]

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
        # Label on the deflated series (roadmap: "on deflated price"), so a
        # "crash" means a real fall in what the crop buys, not a nominal wobble.
        fwd_min = pr.shift(-1).rolling(HORIZON_DAYS, min_periods=3).min().shift(
            -(HORIZON_DAYS - 1)
        )
        df["fwd_drop_pct"] = fwd_min / pr - 1.0
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
    return feature_context_asof(date)[0]


def feature_context_asof(date) -> tuple[pd.Series, pd.Series]:
    """(row, medians) as of `date`. Medians use only data up to `date`, so the
    "is this value high or low" phrasing in scoring carries no lookahead."""
    date = pd.Timestamp(date).normalize()
    df = build_features(with_target=False).loc[:date]
    # Drop the warm-up period where rolling features are still NaN.
    ready = df.dropna(subset=FEATURE_COLS)
    if ready.empty:
        raise ValueError(
            f"not enough history before {date.date()} to score "
            "(need ~1 year of data for the seasonal features)"
        )
    return ready.iloc[-1], ready[FEATURE_COLS].median()
