"""Seed sqlite with a plausible ~9-year synthetic history so the whole pipeline
(features → model → alert → backtest → API) can be exercised without waiting on
the real downloads.

Also the roadmap's demo-day safety net ("seed clean demo data — don't rely on
messy real data live"). Real ingest overwrites these tables.

    python -m scripts.seed_demo
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bhav.config import (
    CROP,
    DISTRICT,
    HISTORY_START,
    NDVI_COMPOSITE_DAYS,
    NDVI_MATURITY_THRESHOLD,
    NDVI_MIN_CLEAR_FRAC,
)
from bhav.db import init_db, write_df
from bhav.warehouses import seed_warehouses

RNG = np.random.default_rng(42)


def _dates() -> pd.DatetimeIndex:
    return pd.date_range(HISTORY_START, pd.Timestamp.today().normalize(), freq="D")


def _seasonal(idx, phase, amp, base):
    doy = np.asarray(idx.dayofyear)
    return base + amp * np.sin(2 * np.pi * (doy / 365.25 + phase))


def _seed_ndvi_composites(idx: pd.DatetimeIndex, daily: pd.Series) -> None:
    """Emit 10-day composites with monsoon cloud gaps, matching the real ingest.

    The synthetic path deliberately mirrors Sentinel-2's actual cadence — and
    drops composites during the June–September cloud season — so the forward-fill
    and `ndvi_obs_age_days` code is exercised offline exactly as it is on real
    data, instead of only ever seeing a perfect daily series.
    """
    s = pd.Series(daily.to_numpy(), index=idx)
    rows = []
    for start in pd.date_range(idx.min(), idx.max(), freq=f"{NDVI_COMPOSITE_DAYS}D"):
        window = s.loc[start:start + pd.Timedelta(days=NDVI_COMPOSITE_DAYS - 1)]
        if window.empty:
            continue
        # Monsoon months are mostly cloud; a composite often fails outright.
        clear = 0.25 + 0.7 * RNG.random() if start.month in (6, 7, 8, 9) \
            else 0.7 + 0.3 * RNG.random()
        if clear < NDVI_MIN_CLEAR_FRAC:
            continue
        value = float(window.mean())
        rows.append({
            "district": DISTRICT,
            "date": start.strftime("%Y-%m-%d"),
            "value": round(value, 4),
            # Share of the belt already dried down past the maturity cut. Logistic
            # in the gap between the belt mean and the threshold.
            "pct_mature": round(
                float(1 / (1 + np.exp((value - NDVI_MATURITY_THRESHOLD) / 0.06))), 4),
            "clear_frac": round(clear, 3),
            "obs_date": window.index.max().strftime("%Y-%m-%d"),
            "n_obs": int(RNG.integers(1, 5)),
        })
    write_df(pd.DataFrame(rows), "ndvi")


def _has_real_ndvi() -> bool:
    """True when the ndvi table holds fetched Sentinel-2 composites."""
    from bhav.db import read_df

    try:
        df = read_df("SELECT COUNT(*) AS n, MAX(n_obs) AS scenes FROM ndvi")
    except Exception:
        return False
    return bool(df.loc[0, "n"]) and pd.notna(df.loc[0, "scenes"])


def _has_real_weather() -> bool:
    """True when the weather table holds the fetched Open-Meteo archive — the
    humidity/ET0 columns only ever come from the real ingest or this seeder,
    so presence of a non-null et0 across many rows marks it as populated."""
    from bhav.db import read_df

    try:
        df = read_df("SELECT COUNT(et0) AS n FROM weather")
    except Exception:
        return False
    return bool(df.loc[0, "n"])


def _has_real_mandi() -> bool:
    """True when mandi_price holds the fetched Agmarknet export — the synthetic
    seed writes a single market, the real one carries 20+."""
    from bhav.db import read_df

    try:
        df = read_df("SELECT COUNT(DISTINCT market) AS n FROM mandi_price")
    except Exception:
        return False
    return int(df.loc[0, "n"] or 0) > 1


def seed(force_ndvi: bool = False, force_weather: bool = False,
         force_mandi: bool = False) -> None:
    init_db()
    idx = _dates()
    n = len(idx)

    # NDVI: two onion crops a year (kharif + rabi), noisy.
    ndvi = _seasonal(idx, 0.05, 0.18, 0.5) + 0.06 * np.sin(4 * np.pi * idx.dayofyear / 365.25)
    ndvi += RNG.normal(0, 0.03, n)
    ndvi = np.clip(pd.Series(ndvi).rolling(7, min_periods=1, center=True).mean(), 0.1, 0.9)
    if _has_real_ndvi() and not force_ndvi:
        print("ndvi: real Sentinel-2 composites present — left untouched "
              "(--force-ndvi to overwrite)")
    else:
        _seed_ndvi_composites(idx, ndvi)

    # Weather — including humidity and ET0, so the overlay's harvest-window and
    # rot-risk features are exercised offline exactly as on the real archive.
    if _has_real_weather() and not force_weather:
        print("weather: real Open-Meteo archive present — left untouched "
              "(--force-weather to overwrite)")
    else:
        tmax = _seasonal(idx, -0.30, 6.0, 33.0) + RNG.normal(0, 1.5, n)
        tmin = tmax - RNG.uniform(9, 14, n)
        monsoon = np.asarray((idx.month >= 6) & (idx.month <= 9))
        rain = np.where(monsoon, RNG.gamma(2.0, 6.0, n), RNG.gamma(0.3, 2.0, n))
        # Humidity tracks the monsoon and the day's rain.
        hum = np.clip(
            _seasonal(idx, -0.05, 18.0, 58.0) + 0.9 * np.minimum(rain, 20)
            + RNG.normal(0, 6, n), 12, 97)
        write_df(pd.DataFrame({
            "district": DISTRICT, "date": idx.strftime("%Y-%m-%d"),
            "rainfall": rain.round(1),
            "rain_hours": np.where(rain >= 1.0, RNG.uniform(1, 12, n), 0.0).round(1),
            "temp_max": tmax.round(1), "temp_min": tmin.round(1),
            "temp_mean": ((tmax + tmin) / 2).round(1),
            "humidity_max": np.clip(hum + RNG.uniform(5, 14, n), 15, 100).round(0),
            "humidity_min": np.clip(hum - RNG.uniform(10, 25, n), 5, 95).round(0),
            "humidity_mean": hum.round(0),
            # Drying power falls as humidity rises.
            "et0": np.clip(7.5 - 0.05 * hum + RNG.normal(0, 0.6, n), 0.5, 11).round(2),
            "wind_max": np.clip(RNG.gamma(4, 4, n), 3, 45).round(1),
        }), "weather")

    # Price: mean-reverting around a seasonal curve, with harvest-glut crashes
    # every year in Apr–May and Oct–Nov when NDVI has just fallen.
    if _has_real_mandi() and not force_mandi:
        print("mandi_price: real Agmarknet export present — left untouched "
              "(--force-mandi to overwrite)")
        seed_warehouses()
        print(f"seeded {n} days  {idx.min().date()} .. {idx.max().date()}")
        return

    price = np.zeros(n)
    price[0] = 1600.0
    seas = _seasonal(idx, 0.15, 420.0, 1650.0)
    ndvi_drop = pd.Series(ndvi.to_numpy()).diff(21).fillna(0).to_numpy()
    glut_left = 0
    for t in range(1, n):
        # a harvest glut is a transient regime: it triggers occasionally when
        # the crop has just come off, then decays over ~3 weeks.
        if (idx[t].month in (4, 5, 10, 11) and ndvi_drop[t] < -0.05
                and glut_left == 0 and RNG.random() < 0.08):
            glut_left = RNG.integers(14, 25)
        glut = -RNG.uniform(28, 45) if glut_left > 0 else 0.0
        glut_left = max(glut_left - 1, 0)
        reversion = 0.06 * (seas[t] - price[t - 1])
        price[t] = price[t - 1] + reversion + glut + RNG.normal(0, 45)
    price = np.clip(price, 650, 6500)
    arrivals = np.clip(1200 - 1500 * ndvi_drop + RNG.normal(0, 250, n), 100, None)
    write_df(pd.DataFrame({
        "district": DISTRICT, "crop": CROP, "date": idx.strftime("%Y-%m-%d"),
        "market": "Lasalgaon", "variety": "Other",
        "arrivals_tonnes": arrivals.round(0),
        "price_min": (price * 0.78).round(0),
        "price_modal": price.round(0),
        "price_max": (price * 1.22).round(0),
    }), "mandi_price")

    seed_warehouses()
    print(f"seeded {n} days  {idx.min().date()} .. {idx.max().date()}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--force-ndvi", action="store_true",
                    help="overwrite fetched Sentinel-2 composites with synthetic ones")
    ap.add_argument("--force-weather", action="store_true",
                    help="overwrite the fetched Open-Meteo archive with synthetic data")
    ap.add_argument("--force-mandi", action="store_true",
                    help="overwrite the fetched Agmarknet export with synthetic prices")
    args = ap.parse_args()
    seed(force_ndvi=args.force_ndvi, force_weather=args.force_weather,
         force_mandi=args.force_mandi)
