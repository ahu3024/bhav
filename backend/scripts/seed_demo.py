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

from bhav.config import CROP, DISTRICT, HISTORY_START
from bhav.db import init_db, write_df
from bhav.warehouses import seed_warehouses

RNG = np.random.default_rng(42)


def _dates() -> pd.DatetimeIndex:
    return pd.date_range(HISTORY_START, pd.Timestamp.today().normalize(), freq="D")


def _seasonal(idx, phase, amp, base):
    doy = np.asarray(idx.dayofyear)
    return base + amp * np.sin(2 * np.pi * (doy / 365.25 + phase))


def seed() -> None:
    init_db()
    idx = _dates()
    n = len(idx)

    # NDVI: two onion crops a year (kharif + rabi), noisy.
    ndvi = _seasonal(idx, 0.05, 0.18, 0.5) + 0.06 * np.sin(4 * np.pi * idx.dayofyear / 365.25)
    ndvi += RNG.normal(0, 0.03, n)
    ndvi = np.clip(pd.Series(ndvi).rolling(7, min_periods=1, center=True).mean(), 0.1, 0.9)
    write_df(pd.DataFrame({"district": DISTRICT, "date": idx.strftime("%Y-%m-%d"),
                           "value": ndvi.to_numpy()}), "ndvi")

    # Weather
    tmax = _seasonal(idx, -0.30, 6.0, 33.0) + RNG.normal(0, 1.5, n)
    tmin = tmax - RNG.uniform(9, 14, n)
    monsoon = np.asarray((idx.month >= 6) & (idx.month <= 9))
    rain = np.where(monsoon, RNG.gamma(2.0, 6.0, n), RNG.gamma(0.3, 2.0, n))
    write_df(pd.DataFrame({"district": DISTRICT, "date": idx.strftime("%Y-%m-%d"),
                           "rainfall": rain.round(1), "temp_max": tmax.round(1),
                           "temp_min": tmin.round(1)}), "weather")

    # Price: mean-reverting around a seasonal curve, with harvest-glut crashes
    # every year in Apr–May and Oct–Nov when NDVI has just fallen.
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
        "market": "Lasalgaon", "price_per_quintal": price.round(0),
        "arrivals_tonnes": arrivals.round(0),
    }), "mandi_price")

    seed_warehouses()
    print(f"seeded {n} days  {idx.min().date()} .. {idx.max().date()}")


if __name__ == "__main__":
    seed()
