"""Load the raw CSVs produced by the ingest modules into sqlite."""

from __future__ import annotations

import pandas as pd

from ..config import CROP, DISTRICT, RAW_DIR
from ..db import init_db, write_df
from .ndvi import OUT_CSV as NDVI_CSV
from .mandi import OUT_CSV as MANDI_CSV
from .weather import OUT_CSV as WEATHER_CSV


def _read(path):
    if not path.exists():
        raise FileNotFoundError(f"missing {path} — run the matching fetch first")
    df = pd.read_csv(path, parse_dates=["date"])
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df


def load_all() -> None:
    init_db()

    ndvi = _read(NDVI_CSV)[["district", "date", "value"]]
    write_df(ndvi, "ndvi")
    print(f"ndvi        {len(ndvi):>6} rows")

    weather = _read(WEATHER_CSV)[
        ["district", "date", "rainfall", "temp_max", "temp_min"]
    ]
    write_df(weather, "weather")
    print(f"weather     {len(weather):>6} rows")

    mandi = _read(MANDI_CSV)
    if "crop" not in mandi:
        mandi["crop"] = CROP
    if "district" not in mandi:
        mandi["district"] = DISTRICT
    if "arrivals_tonnes" not in mandi:
        mandi["arrivals_tonnes"] = pd.NA
    mandi = mandi[
        ["district", "crop", "date", "market",
         "price_per_quintal", "arrivals_tonnes"]
    ]
    write_df(mandi, "mandi_price")
    print(f"mandi_price {len(mandi):>6} rows")

    from ..warehouses import seed_warehouses
    seed_warehouses()
    print("warehouses  seeded")


if __name__ == "__main__":
    load_all()
