"""Load the raw CSVs produced by the ingest modules into sqlite."""

from __future__ import annotations

import pandas as pd

from ..config import CROP, DISTRICT, RAW_DIR
from ..db import init_db, write_df
from .ndvi import COLUMNS as NDVI_COLUMNS, OUT_CSV as NDVI_CSV
from .cpi import OUT_CSV as CPI_CSV
from .mandi import OUT_CSV as MANDI_CSV
from .weather import COLUMNS as WEATHER_COLUMNS, OUT_CSV as WEATHER_CSV


def _read(path):
    if not path.exists():
        raise FileNotFoundError(f"missing {path} — run the matching fetch first")
    df = pd.read_csv(path, parse_dates=["date"])
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df


def load_ndvi() -> int:
    """Load just the Sentinel-2 composites — useful when NDVI is the only
    source that has been re-fetched."""
    init_db()
    ndvi = _read(NDVI_CSV)
    # Tolerate a CSV from the older single-column export: the composite extras
    # are optional and features.py degrades without them.
    for col in NDVI_COLUMNS:
        if col not in ndvi:
            ndvi[col] = pd.NA
    ndvi = ndvi[NDVI_COLUMNS]
    write_df(ndvi, "ndvi")
    print(f"ndvi        {len(ndvi):>6} composites "
          f"({ndvi['date'].min()} .. {ndvi['date'].max()})")
    return len(ndvi)


def load_weather() -> int:
    """Load just the Open-Meteo daily archive."""
    init_db()
    weather = _read(WEATHER_CSV)
    for col in WEATHER_COLUMNS:
        if col not in weather:
            weather[col] = pd.NA
    weather = weather[WEATHER_COLUMNS]
    write_df(weather, "weather")
    print(f"weather     {len(weather):>6} days "
          f"({weather['date'].min()} .. {weather['date'].max()})")
    return len(weather)


MANDI_COLUMNS = [
    "district", "crop", "date", "market", "variety",
    "arrivals_tonnes", "price_min", "price_modal", "price_max",
]


def load_mandi() -> int:
    """Load the Agmarknet export. Accepts the current column set and the older
    `price_per_quintal` shape, plus a hand-made export that only has a modal."""
    init_db()
    mandi = _read(MANDI_CSV)

    if "price_modal" not in mandi and "price_per_quintal" in mandi:
        mandi = mandi.rename(columns={"price_per_quintal": "price_modal"})
    for col, default in (("crop", CROP), ("district", DISTRICT),
                         ("variety", "Other"), ("arrivals_tonnes", pd.NA),
                         ("price_min", pd.NA), ("price_max", pd.NA)):
        if col not in mandi:
            mandi[col] = default
    if "price_modal" not in mandi:
        raise ValueError(
            f"{MANDI_CSV} needs a price_modal (or price_per_quintal) column")

    mandi = mandi[MANDI_COLUMNS]
    # The primary key is (district, crop, date, market, variety) — collapse any
    # duplicate lots so the load can't fail on a repeated print.
    mandi = (
        mandi.groupby(["district", "crop", "date", "market", "variety"],
                      as_index=False)
        .agg(arrivals_tonnes=("arrivals_tonnes", "sum"),
             price_min=("price_min", "min"),
             price_modal=("price_modal", "mean"),
             price_max=("price_max", "max"))
    )
    write_df(mandi, "mandi_price")
    print(f"mandi_price {len(mandi):>6} rows "
          f"({mandi['date'].min()} .. {mandi['date'].max()}, "
          f"{mandi['market'].nunique()} markets)")
    return len(mandi)


def load_cpi() -> int:
    """Load the CPI table used for deflation. Optional — prices.py treats a
    missing table as "no deflation" rather than an error."""
    init_db()
    if not CPI_CSV.exists():
        print("cpi         (absent — prices stay nominal)")
        return 0
    cpi = pd.read_csv(CPI_CSV)
    cpi["estimated"] = cpi.get("estimated", False).astype(int)
    write_df(cpi[["year", "cpi", "estimated"]], "cpi")
    print(f"cpi         {len(cpi):>6} years")
    return len(cpi)


def load_all() -> None:
    init_db()
    load_ndvi()
    load_weather()

    load_mandi()
    load_cpi()

    from ..warehouses import seed_warehouses
    seed_warehouses()
    print("warehouses  seeded")


if __name__ == "__main__":
    load_all()
